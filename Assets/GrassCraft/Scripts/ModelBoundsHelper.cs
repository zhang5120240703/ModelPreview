using System;
using UnityEngine;

namespace GrassCraft
{
    public static class ModelBoundsHelper
    {
        public static Bounds Normalize(Transform content, float targetSize = 2f)
        {
            var renderers = content.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0) throw new InvalidOperationException("模型中没有可显示的网格。");
            // Renderer.bounds may not be initialized for an inactive staging hierarchy.
            // Transform local mesh bounds explicitly so off-center nested meshes are included.
            var bounds = new Bounds();
            bool initialized = false;
            foreach (var renderer in renderers)
            {
                var local = renderer.localBounds;
                for (int i = 0; i < 8; i++)
                {
                    var corner = local.center + Vector3.Scale(local.extents,
                        new Vector3((i & 1) == 0 ? -1 : 1, (i & 2) == 0 ? -1 : 1, (i & 4) == 0 ? -1 : 1));
                    var world = renderer.localToWorldMatrix.MultiplyPoint3x4(corner);
                    if (!initialized) { bounds = new Bounds(world, Vector3.zero); initialized = true; }
                    else bounds.Encapsulate(world);
                }
            }
            float size = Mathf.Max(bounds.size.x, bounds.size.y, bounds.size.z);
            if (float.IsNaN(size) || float.IsInfinity(size) || size < 0.000001f)
                throw new InvalidOperationException("模型尺寸无效，无法计算展示范围。");
            float scale = targetSize / size;
            content.localScale *= scale;
            content.position -= bounds.center * scale;
            return new Bounds(Vector3.zero, bounds.size * scale);
        }
    }
}
