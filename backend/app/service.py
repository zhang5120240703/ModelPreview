import asyncio
import json
import logging
from pathlib import Path
from .glb import validate_glb

log = logging.getLogger(__name__)


class ReconstructionWorker:
    def __init__(self, settings, store, provider):
        self.settings, self.store, self.provider = settings, store, provider

    async def run(self):
        while True:
            for task_id in self.store.pending():
                await self.process(task_id)
            await asyncio.sleep(0.2)

    async def process(self, task_id):
        row = self.store.get(task_id)
        folder = self.settings.data_dir / task_id
        partial = folder / 'model.part'
        try:
            if row['provider'] != self.settings.provider:
                raise ValueError('Provider 配置已改变，旧任务未自动重提交')
            if row['status']=='processing' and not row['remote_id']:
                raise ValueError('服务在提交时中断；为避免重复付费，请先在平台核实任务')
            self.store.update(task_id,status='processing')
            async with asyncio.timeout(self.settings.task_timeout_seconds):
                remote_id = row['remote_id']
                if not remote_id:
                    remote_id = await self.provider.create([folder / p for p in json.loads(row['images'])])
                    self.store.update(task_id,remote_id=remote_id)
                while True:
                    result = await self.provider.poll(remote_id)
                    if result.status=='failed': raise ValueError(result.error or '建模失败')
                    if result.status=='succeeded':
                        if not result.model_url: raise ValueError('建模成功但缺少 GLB 下载地址')
                        await self.provider.download(result.model_url,partial)
                        await asyncio.to_thread(validate_glb,partial)
                        partial.replace(folder / 'model.glb')
                        self.store.update(task_id,status='succeeded',progress=100)
                        return
                    # Keep <100 until the model is safely stored locally.
                    self.store.update(task_id,progress=min(result.progress,99) if result.progress is not None else None)
                    await asyncio.sleep(self.settings.poll_interval_seconds)
        except asyncio.CancelledError:
            raise  # SQLite state is recovered next startup; no blind resubmission.
        except TimeoutError:
            self.store.update(task_id,status='failed',error='建模超时；远程任务可能仍在运行，请在平台核实')
        except Exception as exc:
            # Avoid leaking bearer tokens, signed URLs or local paths in transport errors.
            message = str(exc)[:600] if isinstance(exc,(ValueError,NotImplementedError)) else '建模服务或网络异常，请检查服务器日志和平台任务'
            log.warning('Task %s failed (%s)',task_id,type(exc).__name__)
            self.store.update(task_id,status='failed',error=message)
        finally:
            partial.unlink(missing_ok=True)
