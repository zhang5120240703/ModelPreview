using UnityEngine;
using UnityEngine.Rendering;

namespace GrassCraft
{
    public sealed class PreviewBootstrap : MonoBehaviour
    {
        void Awake()
        {
            gameObject.name = "GrassCraftPreview";
            Application.targetFrameRate = 60;
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(.55f,.55f,.55f);
            RenderSettings.fog = false;
            var cameraObject = new GameObject("Preview Camera", typeof(Camera), typeof(AudioListener));
            var camera = cameraObject.GetComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(.18f,.20f,.21f);
            camera.fieldOfView = 40;
            cameraObject.tag = "MainCamera";
            var key = new GameObject("Key Light", typeof(Light));
            var light = key.GetComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.5f;
            light.shadows = LightShadows.None;
            key.transform.rotation = Quaternion.Euler(40,-35,0);
            var fill = new GameObject("Fill Light", typeof(Light)).GetComponent<Light>();
            fill.type = LightType.Directional;
            fill.intensity = .6f;
            fill.shadows = LightShadows.None;
            fill.transform.rotation = Quaternion.Euler(20,130,0);
            var loader = gameObject.AddComponent<ModelLoader>();
            var viewer = gameObject.AddComponent<ModelViewerController>();
            viewer.loader = loader;
            viewer.viewCamera = camera;
            var api = gameObject.AddComponent<ReconstructionApiClient>();
            var ui = gameObject.AddComponent<ModelPreviewUI>();
            ui.loader = loader; ui.viewer = viewer; ui.api = api;
        }
    }
}
