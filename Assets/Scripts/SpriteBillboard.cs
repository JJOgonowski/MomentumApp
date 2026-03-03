using UnityEngine;

/// <summary>
/// Billboard component — makes a 2D sprite quad always face the active camera.
///
/// Mode options
/// ------------
/// Full          : rotates on all axes so the quad faces the camera exactly
///                 (classic billboard, best for isolated objects like a ship miniature).
/// AxisY         : rotates only around the Y axis, keeping the sprite upright in world
///                 space (good for tall objects like a glasses sprite on a desk).
/// CameraForward : aligns with the camera's forward projection onto the XZ plane,
///                 useful when the camera is mostly top-down.
///
/// Usage
/// -----
/// 1. Create a 3D quad (GameObject > 3D Object > Quad).
/// 2. Assign your sprite texture to a material that uses the SpriteLitNormalMap
///    shader (or any transparent unlit/lit shader).
/// 3. Attach this component.
/// 4. Choose the billboard Mode that suits your object.
/// </summary>
public class SpriteBillboard : MonoBehaviour
{
    public enum BillboardMode
    {
        /// <summary>Quad always faces the camera on all axes (spherical billboard).</summary>
        Full,

        /// <summary>Quad rotates only around Y, staying vertically upright.</summary>
        AxisY,

        /// <summary>Quad faces the camera's XZ-projected forward direction.</summary>
        CameraForward
    }

    [Tooltip("How the sprite should orient itself relative to the camera.")]
    public BillboardMode mode = BillboardMode.Full;

    [Tooltip("When true, the sprite flips its X scale to always show the 'front' side.")]
    public bool autoFlip = false;

    // -----------------------------------------------------------------------

    private Transform _cam;

    private void Start()
    {
        _cam = Camera.main != null ? Camera.main.transform : null;
    }

    private void LateUpdate()
    {
        if (_cam == null)
        {
            _cam = Camera.main != null ? Camera.main.transform : null;
            if (_cam == null) return;
        }

        switch (mode)
        {
            case BillboardMode.Full:
                transform.rotation = _cam.rotation;
                break;

            case BillboardMode.AxisY:
                Vector3 dirY = _cam.position - transform.position;
                dirY.y = 0f;
                if (dirY.sqrMagnitude > 0.0001f)
                    transform.rotation = Quaternion.LookRotation(dirY);
                break;

            case BillboardMode.CameraForward:
                Vector3 fwd = _cam.forward;
                fwd.y = 0f;
                if (fwd.sqrMagnitude > 0.0001f)
                    transform.rotation = Quaternion.LookRotation(fwd);
                break;
        }

        if (autoFlip)
        {
            // Flip so the texture always shows the front face
            Vector3 scale = transform.localScale;
            float dot = Vector3.Dot(transform.right, _cam.position - transform.position);
            scale.x = Mathf.Abs(scale.x) * (dot < 0 ? -1f : 1f);
            transform.localScale = scale;
        }
    }
}
