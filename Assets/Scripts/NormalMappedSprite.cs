using UnityEngine;

/// <summary>
/// Configures a SpriteRenderer (or a MeshRenderer on a quad) so that it uses a
/// normal-mapped lit material, giving a 2D sprite the illusion of 3D depth.
///
/// How the 3D illusion works
/// -------------------------
/// A *normal map* encodes per-pixel surface orientation.  When a directional or
/// point light shines on the sprite, the shader reads the normal map and computes
/// highlights and shadows based on those encoded normals — making a flat image look
/// like it has bumps, ridges and cavities.  Combine this with:
///
///   • A billboard component (SpriteBillboard) so the sprite always faces the camera.
///   • A well-placed directional light (e.g. top-left at ~45 °).
///   • A subtle ambient occlusion baked into the albedo/diffuse texture.
///
/// Result: the coffee cup, glasses or ship miniature sprite will appear to have real
/// 3D volume even though it is a flat quad.
///
/// Setup
/// -----
/// 1. In your project create a material that uses the *SpriteLitNormalMap* shader
///    (Assets/Shaders/SpriteLitNormalMap.shader).
/// 2. Assign the albedo (colour) texture and the matching normal-map texture.
/// 3. Attach this component to the same GameObject as the quad/SpriteRenderer.
/// 4. Drag the material into <see cref="litMaterial"/>.
/// 5. Drag the normal map texture into <see cref="normalMap"/>.
/// 6. Optionally adjust <see cref="normalStrength"/> (1 = baked strength, >1 exaggerated).
///
/// Note: if you are using Unity's 2D URP renderer you can instead set the sprite's
/// material to "Sprite-Lit-Default" and attach a secondary texture with the "_NormalMap"
/// role — no custom shader required.  This script handles the 3D (non-2D-renderer)
/// pipeline case.
/// </summary>
[RequireComponent(typeof(Renderer))]
public class NormalMappedSprite : MonoBehaviour
{
    [Header("Material")]
    [Tooltip("Material using the SpriteLitNormalMap shader (or any lit sprite shader " +
             "that accepts _NormalMap and _NormalStrength properties).")]
    public Material litMaterial;

    [Header("Textures")]
    [Tooltip("The albedo/colour texture of the sprite.")]
    public Texture2D albedoTexture;

    [Tooltip("The normal map texture for this sprite (import as 'Normal map' in Unity).")]
    public Texture2D normalMap;

    [Header("Lighting")]
    [Tooltip("Multiplier applied to the normal map strength. " +
             "1 = natural, 2 = exaggerated 3-D look, 0 = flat.")]
    [Range(0f, 4f)]
    public float normalStrength = 1f;

    [Tooltip("Base tint colour applied to the albedo (white = no tint).")]
    public Color tintColor = Color.white;

    // -----------------------------------------------------------------------
    // Internal property IDs (cached for performance)
    // -----------------------------------------------------------------------
    private static readonly int PropMainTex       = Shader.PropertyToID("_MainTex");
    private static readonly int PropNormalMap     = Shader.PropertyToID("_NormalMap");
    private static readonly int PropNormalStrength= Shader.PropertyToID("_NormalStrength");
    private static readonly int PropColor         = Shader.PropertyToID("_Color");

    // -----------------------------------------------------------------------

    private Renderer _renderer;
    private MaterialPropertyBlock _mpb;

    private void Awake()
    {
        _renderer = GetComponent<Renderer>();
        _mpb      = new MaterialPropertyBlock();

        ApplyMaterial();
    }

    private void OnValidate()
    {
        // Live-update in the Editor when inspector values change.
        if (_renderer == null) _renderer = GetComponent<Renderer>();
        if (_mpb      == null) _mpb      = new MaterialPropertyBlock();
        ApplyMaterial();
    }

    // -----------------------------------------------------------------------

    /// <summary>
    /// Assigns the lit material to the renderer and pushes texture / parameter
    /// overrides via a MaterialPropertyBlock (avoids creating new material
    /// instances and causing unnecessary draw-call breaks).
    /// </summary>
    public void ApplyMaterial()
    {
        if (litMaterial != null)
            _renderer.sharedMaterial = litMaterial;

        _renderer.GetPropertyBlock(_mpb);

        if (albedoTexture != null) _mpb.SetTexture(PropMainTex,        albedoTexture);
        if (normalMap     != null) _mpb.SetTexture(PropNormalMap,      normalMap);

        _mpb.SetFloat(PropNormalStrength, normalStrength);
        _mpb.SetColor(PropColor,          tintColor);

        _renderer.SetPropertyBlock(_mpb);
    }

    // -----------------------------------------------------------------------
    // Public helpers called from DeskSceneManager
    // -----------------------------------------------------------------------

    /// <summary>Changes the normal-map strength at runtime (e.g. for a demo slider).</summary>
    public void SetNormalStrength(float value)
    {
        normalStrength = Mathf.Clamp(value, 0f, 4f);
        ApplyMaterial();
    }
}
