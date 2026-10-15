using UnityEngine;
using UnityEngine.InputSystem;
using TouchPhase = UnityEngine.InputSystem.TouchPhase;

namespace GrassCraft
{
    public sealed class ModelViewerController : MonoBehaviour
    {
        public Camera viewCamera;
        public ModelLoader loader;
        public bool autoRotate = true;
        public Rect blockedScreenRect;
        float yaw = 25, pitch = -15, distance = 5, fitDistance = 5;
        bool dragging;
        bool touchActive;
        bool pinching;
        float previousPinch;
        Bounds lastBounds = new Bounds(Vector3.zero, Vector3.one * 2);

        void Start() { loader.Loaded += OnLoaded; ResetView(); }
        void OnDestroy() { if (loader != null) loader.Loaded -= OnLoaded; }
        void OnLoaded(Bounds bounds) { Fit(bounds); }

        public void Fit(Bounds bounds)
        {
            lastBounds = bounds;
            float vertical = viewCamera.fieldOfView * Mathf.Deg2Rad / 2;
            float horizontal = Mathf.Atan(Mathf.Tan(vertical) * viewCamera.aspect);
            fitDistance = bounds.extents.magnitude / Mathf.Sin(Mathf.Min(vertical, horizontal)) * 1.15f;
            ResetView();
        }
        public void Refit() { Fit(lastBounds); }
        public void ResetView() { yaw = 25; pitch = -15; distance = fitDistance; ApplyView(); }
        public void Rotate(Vector2 delta)
        {
            yaw -= delta.x * .25f;
            pitch += delta.y * .25f;
        }
        public void Zoom(float logarithmicDelta)
        {
            distance = Mathf.Clamp(distance * Mathf.Exp(-logarithmicDelta), fitDistance * .55f, fitDistance * 3f);
        }
        bool InViewer(Vector2 p) => !blockedScreenRect.Contains(p) && viewCamera.pixelRect.Contains(p);

        void Update()
        {
            bool interacting = HandleTouch();
            var mouse = Mouse.current;
            if (!interacting && mouse != null)
            {
                if (mouse.leftButton.wasPressedThisFrame) dragging = InViewer(mouse.position.ReadValue());
                if (!mouse.leftButton.isPressed) dragging = false;
                if (dragging) { Rotate(mouse.delta.ReadValue()); interacting = true; }
                if (InViewer(mouse.position.ReadValue())) Zoom(mouse.scroll.ReadValue().y * .001f);
            }
            if (autoRotate && !interacting && !loader.IsLoading) yaw += 12 * Time.unscaledDeltaTime;
            ApplyView();
        }

        bool HandleTouch()
        {
            var screen = Touchscreen.current;
            if (screen == null) return false;
            UnityEngine.InputSystem.Controls.TouchControl first = null, second = null;
            foreach (var touch in screen.touches)
            {
                if (!touch.press.isPressed) continue;
                if (first == null) first = touch; else { second = touch; break; }
            }
            if (first == null) { touchActive = false; pinching = false; return false; }
            if (first.phase.ReadValue() == TouchPhase.Began) touchActive = InViewer(first.position.ReadValue());
            if (!touchActive) return true;
            if (second != null)
            {
                if (!InViewer(second.startPosition.ReadValue())) return true;
                float separation = Vector2.Distance(first.position.ReadValue(), second.position.ReadValue());
                if (pinching && previousPinch > 1 && separation > 1) Zoom(Mathf.Log(separation / previousPinch));
                previousPinch = separation; pinching = true;
            }
            else
            {
                if (!pinching) Rotate(first.delta.ReadValue());
                pinching = false;
            }
            return true;
        }
        void ApplyView()
        {
            if (viewCamera == null || loader == null || loader.Pivot == null) return;
            loader.Pivot.localRotation = Quaternion.Euler(pitch, yaw, 0);
            viewCamera.transform.position = new Vector3(0, 0, -distance);
            viewCamera.transform.LookAt(Vector3.zero);
            viewCamera.nearClipPlane = .01f;
            viewCamera.farClipPlane = Mathf.Max(100, distance * 5);
        }
    }
}
