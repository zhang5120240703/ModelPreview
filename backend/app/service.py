import asyncio
import json
import logging
from pathlib import Path
from .glb import validate_glb
from .github_publisher import MANIFEST

log = logging.getLogger(__name__)


class ReconstructionWorker:
    def __init__(self, settings, store, provider, publisher=None):
        self.settings, self.store, self.provider = settings, store, provider
        self.publisher=publisher

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
            preparing=row.get('stage') in ('uploading_images','waiting_images') and (folder/MANIFEST).exists()
            if row['status']=='processing' and not row['remote_id'] and not preparing:
                raise ValueError('服务在提交时中断；为避免重复付费，请先在平台核实任务')
            self.store.update(task_id,status='processing')
            if not row['remote_id'] and (folder/MANIFEST).exists():
                if self.publisher is None:raise ValueError('GitHub 上传配置缺失，请配置并重启；尚未提交混元')
                def changed(stage,message):
                    self.store.update(task_id,stage=stage,status_message=message,progress=None)
                changed('uploading_images','正在准备发布本次照片到 GitHub；尚未提交混元')
                await self.publisher.prepare(folder,changed)
            async with asyncio.timeout(self.settings.task_timeout_seconds):
                remote_id = row['remote_id']
                if not remote_id:
                    self.store.update(task_id,stage='submitting',status_message='图片已准备好，正在向建模平台提交任务')
                    remote_id = await self.provider.create([folder / p for p in json.loads(row['images'])])
                    self.store.update(task_id,remote_id=remote_id)
                self.store.update(task_id,stage='generating',status_message='建模任务已提交，正在等待平台生成模型')
                while True:
                    result = await self.provider.poll(remote_id)
                    if result.status=='failed': raise ValueError(result.error or '建模失败')
                    if result.status=='succeeded':
                        if not result.model_url: raise ValueError('建模成功但缺少 GLB 下载地址')
                        self.store.update(task_id,stage='downloading',status_message='平台已完成，正在下载并校验 GLB')
                        await self.provider.download(result.model_url,partial)
                        await asyncio.to_thread(validate_glb,partial)
                        partial.replace(folder / 'model.glb')
                        self.store.update(task_id,status='succeeded',progress=100,stage='completed',status_message='模型文件已生成并保存，可下载或在 Unity 中预览；请检查实际还原效果')
                        return
                    # Keep <100 until the model is safely stored locally.
                    self.store.update(task_id,progress=min(result.progress,99) if result.progress is not None else None)
                    await asyncio.sleep(self.settings.poll_interval_seconds)
        except asyncio.CancelledError:
            raise  # SQLite state is recovered next startup; no blind resubmission.
        except TimeoutError:
            self.store.update(task_id,status='failed',stage='failed',error='建模超时；远程任务可能仍在运行，请在平台核实')
        except Exception as exc:
            # Avoid leaking bearer tokens, signed URLs or local paths in transport errors.
            message = str(exc)[:600] if isinstance(exc,(ValueError,NotImplementedError)) else '建模服务或网络异常，请检查服务器日志和平台任务'
            log.warning('Task %s failed (%s)',task_id,type(exc).__name__)
            self.store.update(task_id,status='failed',stage='failed',error=message)
        finally:
            partial.unlink(missing_ok=True)
