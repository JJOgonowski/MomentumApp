using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Procedurally constructs the desk scene at runtime.
///
/// Hierarchy created
/// -----------------
/// Scene Root
///   Desk          (1×0.05×0.6 grey box representing the desk surface)
///   MapQuad       (flat Quad stretched over the desk top — assign map texture in Inspector)
///   Props/
///     Glasses     (billboard sprite quad + NormalMappedSprite + SpriteBillboard)
///     CoffeeCup   (billboard sprite quad + NormalMappedSprite + SpriteBillboard)
///     ShipMini    (billboard sprite quad + NormalMappedSprite + SpriteBillboard)
///   MainCamera    (with CameraController attached)
///   DirectionalLight
///
/// Assign your sprite textures and normal maps in the Inspector before entering
/// Play mode.  The material used by all props is <see cref="spriteLitMaterial"/>;
/// you should create a single material using the SpriteLitNormalMap shader and
/// assign it here (all texture overrides are applied per-object via
/// MaterialPropertyBlocks, so they share the material without draw-call conflicts).
/// </summary>
public class DeskSceneManager : MonoBehaviour
{
    // -----------------------------------------------------------------------
    // Inspector fields
    // -----------------------------------------------------------------------

    [Header("Desk & Map")]
    [Tooltip("Texture to display on the flat map quad on top of the desk.")]
    public Texture2D mapTexture;

    [Tooltip("Material for the desk surface (any opaque lit material).")]
    public Material deskMaterial;

    [Tooltip("Material for the flat map quad (unlit or Standard with the map texture).")]
    public Material mapMaterial;

    [Header("Props — shared material")]
    [Tooltip("Material that uses the SpriteLitNormalMap shader. " +
             "All prop quads share this material; textures are set per-object " +
             "via MaterialPropertyBlocks.")]
    public Material spriteLitMaterial;

    [Header("Glasses prop")]
    public Texture2D glassesAlbedo;
    public Texture2D glassesNormal;
    [Range(0f, 4f)] public float glassesNormalStrength = 1.5f;

    [Header("Coffee Cup prop")]
    public Texture2D coffeeCupAlbedo;
    public Texture2D coffeeCupNormal;
    [Range(0f, 4f)] public float coffeeCupNormalStrength = 1.5f;

    [Header("Ship Miniature prop")]
    public Texture2D shipAlbedo;
    public Texture2D shipNormal;
    [Range(0f, 4f)] public float shipNormalStrength = 2f;

    [Header("Camera Start")]
    [Tooltip("Initial camera position.")]
    public Vector3 cameraStartPosition = new Vector3(0f, 3f, -4f);
    [Tooltip("Initial camera Euler angles (pitch, yaw, 0).")]
    public Vector3 cameraStartEuler    = new Vector3(35f, 0f, 0f);

    // -----------------------------------------------------------------------
    // Internal — tracks generated objects so we can regenerate in the Editor
    // -----------------------------------------------------------------------

    private readonly List<GameObject> _generated = new List<GameObject>();

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------

    private void Start()
    {
        BuildScene();
    }

    // -----------------------------------------------------------------------
    // Scene construction
    // -----------------------------------------------------------------------

    /// <summary>
    /// Builds (or rebuilds) all scene objects.  Safe to call multiple times —
    /// previously generated objects are destroyed first.
    /// </summary>
    public void BuildScene()
    {
        // Clean up previous build (e.g. from Editor "Rebuild" button).
        foreach (var go in _generated)
            if (go != null) Destroy(go);
        _generated.Clear();

        BuildDesk();
        BuildMapQuad();
        BuildProps();
        BuildLight();
    }

    // -----------------------------------------------------------------------
    // Desk surface
    // -----------------------------------------------------------------------

    private void BuildDesk()
    {
        // A thin, wide box that represents the desk top.
        var desk = GameObject.CreatePrimitive(PrimitiveType.Cube);
        desk.name = "Desk";
        desk.transform.SetParent(transform, false);
        desk.transform.localPosition = Vector3.zero;
        desk.transform.localScale    = new Vector3(3f, 0.05f, 2f);

        if (deskMaterial != null)
            desk.GetComponent<Renderer>().sharedMaterial = deskMaterial;

        Track(desk);
    }

    // -----------------------------------------------------------------------
    // Flat map quad
    // -----------------------------------------------------------------------

    private void BuildMapQuad()
    {
        var map = GameObject.CreatePrimitive(PrimitiveType.Quad);
        map.name = "MapQuad";
        map.transform.SetParent(transform, false);

        // Lay flat on top of the desk (rotate 90° around X to face up).
        map.transform.localPosition = new Vector3(0f, 0.026f, 0f); // just above desk surface
        map.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
        map.transform.localScale    = new Vector3(2.4f, 1.6f, 1f);

        if (mapMaterial != null)
        {
            var r = map.GetComponent<Renderer>();
            r.sharedMaterial = mapMaterial;
            if (mapTexture != null)
            {
                var mpb = new MaterialPropertyBlock();
                r.GetPropertyBlock(mpb);
                mpb.SetTexture("_MainTex", mapTexture);
                r.SetPropertyBlock(mpb);
            }
        }

        Track(map);
    }

    // -----------------------------------------------------------------------
    // Prop sprites
    // -----------------------------------------------------------------------

    private void BuildProps()
    {
        var propsRoot = new GameObject("Props");
        propsRoot.transform.SetParent(transform, false);
        Track(propsRoot);

        // ---- Glasses (left side of the map) --------------------------------
        CreatePropQuad(
            name:           "Glasses",
            parent:         propsRoot.transform,
            localPos:       new Vector3(-1.4f, 0.35f, -0.5f),
            size:           new Vector2(0.4f, 0.2f),
            albedo:         glassesAlbedo,
            normalMap:      glassesNormal,
            normalStrength: glassesNormalStrength,
            billboardMode:  SpriteBillboard.BillboardMode.AxisY
        );

        // ---- Coffee cup (right side of the map) ----------------------------
        CreatePropQuad(
            name:           "CoffeeCup",
            parent:         propsRoot.transform,
            localPos:       new Vector3(1.4f, 0.4f, 0.4f),
            size:           new Vector2(0.25f, 0.35f),
            albedo:         coffeeCupAlbedo,
            normalMap:      coffeeCupNormal,
            normalStrength: coffeeCupNormalStrength,
            billboardMode:  SpriteBillboard.BillboardMode.AxisY
        );

        // ---- Ship miniature (back-right corner) ----------------------------
        CreatePropQuad(
            name:           "ShipMiniature",
            parent:         propsRoot.transform,
            localPos:       new Vector3(1.1f, 0.55f, -0.7f),
            size:           new Vector2(0.6f, 0.45f),
            albedo:         shipAlbedo,
            normalMap:      shipNormal,
            normalStrength: shipNormalStrength,
            billboardMode:  SpriteBillboard.BillboardMode.Full
        );
    }

    /// <summary>Creates a single prop: a quad with SpriteBillboard + NormalMappedSprite.</summary>
    private GameObject CreatePropQuad(
        string name,
        Transform parent,
        Vector3 localPos,
        Vector2 size,
        Texture2D albedo,
        Texture2D normalMap,
        float normalStrength,
        SpriteBillboard.BillboardMode billboardMode)
    {
        var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
        quad.name = name;
        quad.transform.SetParent(parent, false);
        quad.transform.localPosition = localPos;
        quad.transform.localScale    = new Vector3(size.x, size.y, 1f);

        // Remove the Mesh Collider — props don't need physics.
        var col = quad.GetComponent<Collider>();
        if (col != null) Destroy(col);

        // Billboard
        var billboard  = quad.AddComponent<SpriteBillboard>();
        billboard.mode = billboardMode;

        // Normal-mapped material
        var nms               = quad.AddComponent<NormalMappedSprite>();
        nms.litMaterial       = spriteLitMaterial;
        nms.albedoTexture     = albedo;
        nms.normalMap         = normalMap;
        nms.normalStrength    = normalStrength;

        // ApplyMaterial is called in NormalMappedSprite.Awake(), which runs
        // after this method returns when we're in Play mode.  In Edit mode we
        // call it explicitly so the Editor preview updates immediately.
#if UNITY_EDITOR
        if (!Application.isPlaying)
            nms.ApplyMaterial();
#endif

        Track(quad);
        return quad;
    }

    // -----------------------------------------------------------------------
    // Directional light
    // -----------------------------------------------------------------------

    private void BuildLight()
    {
        // Check if a Directional Light already exists in the scene.
        if (FindObjectOfType<Light>() != null) return;

        var lightGO = new GameObject("DirectionalLight");
        var light   = lightGO.AddComponent<Light>();
        light.type      = LightType.Directional;
        light.intensity = 1.2f;
        light.color     = new Color(1f, 0.95f, 0.85f); // warm afternoon colour

        // Angle from top-left so normal maps show good contrast.
        lightGO.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        Track(lightGO);
    }

    // -----------------------------------------------------------------------
    // Helper
    // -----------------------------------------------------------------------

    private void Track(GameObject go)
    {
        _generated.Add(go);
    }
}
