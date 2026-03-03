using UnityEngine;

/// <summary>
/// First-person-style camera controller for the desk scene.
///
/// Controls:
///   - WASD / Arrow keys  : translate the camera on the X and Z plane (pan)
///   - Mouse scroll wheel : zoom (move camera along its local forward axis)
///   - Middle mouse drag  : pan (translate X / Z without rotating)
///   - Right mouse drag   : orbit / rotate the view
///
/// The camera is kept above the desk so the player always looks down at the map.
/// </summary>
public class CameraController : MonoBehaviour
{
    [Header("Movement")]
    [Tooltip("Speed for keyboard X/Z translation.")]
    public float moveSpeed = 5f;

    [Tooltip("Speed for middle-mouse pan drag.")]
    public float panSpeed = 0.05f;

    [Header("Zoom")]
    [Tooltip("Speed of scroll-wheel zoom.")]
    public float zoomSpeed = 5f;

    [Tooltip("Minimum distance the camera can zoom in to the focus point.")]
    public float minZoom = 1f;

    [Tooltip("Maximum distance the camera can zoom out from the focus point.")]
    public float maxZoom = 20f;

    [Header("Rotation")]
    [Tooltip("Sensitivity of right-mouse-button orbit.")]
    public float rotationSpeed = 100f;

    [Tooltip("Minimum vertical (pitch) angle in degrees.")]
    public float minPitch = 10f;

    [Tooltip("Maximum vertical (pitch) angle in degrees.")]
    public float maxPitch = 85f;

    [Header("Bounds (optional)")]
    [Tooltip("If set, the camera pivot is clamped inside this axis-aligned box.")]
    public Bounds movementBounds = new Bounds(Vector3.zero, new Vector3(10f, 0f, 10f));
    public bool enforceBounds = false;

    // -----------------------------------------------------------------------
    // Private state
    // -----------------------------------------------------------------------

    // Current orbital angles around the pivot point.
    private float _yaw;   // horizontal rotation
    private float _pitch; // vertical rotation

    // Distance from the pivot (used for zoom).
    private float _distance;

    // The world-space point the camera orbits around and pans to.
    private Vector3 _pivot;

    // -----------------------------------------------------------------------

    private void Start()
    {
        // Initialise orbit angles and distance from the camera's current pose.
        Vector3 euler = transform.eulerAngles;
        _yaw   = euler.y;
        _pitch = euler.x;

        // Place pivot in front of (below) the camera at whatever distance is
        // implied by the current position.
        _distance = Mathf.Clamp(
            Vector3.Distance(transform.position, GetDefaultPivot()),
            minZoom, maxZoom);
        _pivot = transform.position + transform.forward * _distance;
    }

    private void Update()
    {
        HandleZoom();
        HandleRotation();
        HandlePan();
        HandleKeyboardMove();
        ApplyTransform();
    }

    // -----------------------------------------------------------------------
    // Input handlers
    // -----------------------------------------------------------------------

    private void HandleZoom()
    {
        float scroll = Input.GetAxis("Mouse ScrollWheel");
        if (Mathf.Abs(scroll) > 0.001f)
        {
            _distance -= scroll * zoomSpeed;
            _distance  = Mathf.Clamp(_distance, minZoom, maxZoom);
        }
    }

    private void HandleRotation()
    {
        if (!Input.GetMouseButton(1)) return; // right mouse button

        _yaw   += Input.GetAxis("Mouse X") * rotationSpeed * Time.deltaTime;
        _pitch -= Input.GetAxis("Mouse Y") * rotationSpeed * Time.deltaTime;
        _pitch  = Mathf.Clamp(_pitch, minPitch, maxPitch);
    }

    private void HandlePan()
    {
        if (!Input.GetMouseButton(2)) return; // middle mouse button

        float dx = -Input.GetAxis("Mouse X") * panSpeed * _distance;
        float dz = -Input.GetAxis("Mouse Y") * panSpeed * _distance;

        // Pan in camera-local X and Z (no vertical drift).
        Vector3 right   = transform.right;
        Vector3 forward = Vector3.Cross(right, Vector3.up).normalized;

        _pivot += right   * dx;
        _pivot += forward * dz;
        ClampPivot();
    }

    private void HandleKeyboardMove()
    {
        float h = Input.GetAxis("Horizontal"); // A/D or Left/Right
        float v = Input.GetAxis("Vertical");   // W/S or Up/Down

        if (Mathf.Abs(h) < 0.001f && Mathf.Abs(v) < 0.001f) return;

        Vector3 right   = transform.right;
        Vector3 forward = Vector3.Cross(right, Vector3.up).normalized;

        _pivot += (right * h + forward * v) * moveSpeed * Time.deltaTime;
        ClampPivot();
    }

    // -----------------------------------------------------------------------
    // Apply final transform
    // -----------------------------------------------------------------------

    private void ApplyTransform()
    {
        Quaternion rotation = Quaternion.Euler(_pitch, _yaw, 0f);
        Vector3 offset      = rotation * new Vector3(0f, 0f, -_distance);

        transform.position = _pivot + offset;
        transform.rotation = rotation;
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private void ClampPivot()
    {
        if (!enforceBounds) return;
        _pivot.x = Mathf.Clamp(_pivot.x,
            movementBounds.center.x - movementBounds.extents.x,
            movementBounds.center.x + movementBounds.extents.x);
        _pivot.z = Mathf.Clamp(_pivot.z,
            movementBounds.center.z - movementBounds.extents.z,
            movementBounds.center.z + movementBounds.extents.z);
    }

    private static Vector3 GetDefaultPivot()
    {
        return Vector3.zero;
    }
}
