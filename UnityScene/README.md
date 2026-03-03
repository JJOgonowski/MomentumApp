# Unity Desk Scene — 3-D Look from 2-D Sprites

A Unity scene showing a first-person view of a desk with a flat map and surrounding
prop objects (glasses, coffee cup, ship miniature) rendered as **2-D billboard sprites**
that appear three-dimensional through normal-map lighting.

---

## Contents

```
Assets/
  Scripts/
    CameraController.cs     — zoom / pan / X-Z move / orbit camera
    SpriteBillboard.cs      — makes a quad face the camera every frame
    NormalMappedSprite.cs   — applies a normal-mapped lit material to a renderer
    DeskSceneManager.cs     — builds the scene hierarchy at runtime
  Shaders/
    SpriteLitNormalMap.shader — custom lit shader with normal-map support (BiRP)
UnityScene/
  README.md                 — this file
```

---

## Approach: Mimicking a 3-D Look on 2-D Sprites

This section explains **why and how** a flat image can look three-dimensional in a
real-time scene.  The illusion rests on three mutually reinforcing pillars.

---

### The core problem

A textured quad (flat rectangle) is detected as flat by the human visual system
as soon as lighting reveals its true geometry.  A real coffee cup, for example, has
a curved surface that catches light differently across its silhouette.  A flat quad
with a coffee-cup texture responds to light as a *flat plane* — the whole surface
brightens and darkens uniformly, which immediately reads as "fake".

The solution is to make each *pixel* of the quad respond to light as if it were
part of a curved, three-dimensional surface.  This is exactly what a **normal map**
achieves.

---

### Pillar 1 — Normal maps: encoding surface orientation per pixel

A **normal map** is a texture where the RGB channels store a 3-D direction vector
(the surface normal) for every pixel:

```
R → X component  (left–right tilt)
G → Y component  (up–down tilt)
B → Z component  (facing forward, always positive)
```

The characteristic blue-purple colour of normal maps comes from the encoding formula
`stored = normal * 0.5 + 0.5`: a flat forward-facing normal (0, 0, 1) encodes to
exactly (0.5, 0.5, 1.0), which in 8-bit RGB is (128, 128, 255).  Where the surface
curves toward the light, the R or G channels deviate from 128, encoding a tilted
normal that will catch more (or less) light from a given direction.

**What the shader does with this** (see `Assets/Shaders/SpriteLitNormalMap.shader`):

1. *Sample* the normal map at the current pixel's UV coordinate.
2. *Unpack* the [0, 1] RGB values back to a [-1, 1] direction vector in
   **tangent space** (the local coordinate frame of the quad's surface).
3. *Scale* the XY components by `_NormalStrength`.  A value of 1 reproduces the
   authored depth; 2 doubles the perceived depth; 0 reduces the sprite to flat.
4. *Transform* the tangent-space normal into **world space** using the
   **TBN matrix** (see below) so it can be compared with a world-space light direction.
5. *Compute* Lambertian diffuse: `NdotL = max(0, dot(worldNormal, lightDir))`.
   Pixels whose encoded normal points toward the light become bright; those angled
   away become dark — exactly mimicking a curved 3-D surface.

#### The TBN matrix

The quad's geometry provides three orthogonal world-space axes:

| Axis | Source |
|------|--------|
| **T** angent | `v.tangent.xyz` transformed to world space |
| **B** itangent | `cross(worldNormal, worldTangent) * handedness` |
| **N** ormal | `v.normal` transformed to world space |

Multiplying the tangent-space sample by `float3x3(T, B, N)` rotates the encoded
direction into the same world space as the directional light, making the lighting
calculation correct regardless of how the quad is oriented in the scene.

#### Generating normal maps for your sprites

Normal maps are usually created from a **height map** (greyscale image where white =
high, black = low) by calculating the gradient at each pixel.  Free options:

- [NormalMap Online](https://cpetry.github.io/NormalMap-Online/) — browser-based,
  drag-and-drop.
- Photoshop → *Filter → 3D → Generate Normal Map*.
- Substance Painter / Designer — industry-standard, free for students.
- Blender → bake a normal map from a high-poly model onto a low-poly sprite.

---

### Pillar 2 — Billboard rotation: hiding the flat edge

Even a perfectly lit sprite destroys the illusion the moment the viewer can see its
edge — a single-pixel-thin line that immediately reveals the object as a flat card.

`SpriteBillboard` (see `Assets/Scripts/SpriteBillboard.cs`) runs in `LateUpdate`
every frame and rotates the quad so that its **front face always points directly at
the camera**.

For the **Full** mode the quad's local +Z is aimed at the camera using
`Quaternion.LookRotation`:

```csharp
// Make the quad's front face (+Z) point toward the camera
Vector3 dirToCamera = _cam.position - transform.position;
transform.rotation = Quaternion.LookRotation(dirToCamera);
```

The implementation in `SpriteBillboard.cs` copies `_cam.rotation` directly, which
works because the shader uses `Cull Off` (both sides rendered).  The
`LookRotation` form above is the equivalent single-sided formulation.

For objects that should stay upright (glasses, coffee cup) the **AxisY** mode
rotates only around the vertical Y axis:

```csharp
Vector3 dirY = _cam.position - transform.position;
dirY.y = 0f;                         // ignore vertical difference
transform.rotation = Quaternion.LookRotation(dirY);
```

This means:
- The viewer can never see the thin edge of the quad.
- The quad tracks the camera smoothly during zoom and pan.
- The sprite's "up" direction remains stable, preventing objects from appearing to
  tip over as the camera moves.

---

### Pillar 3 — Light placement: maximising perceived depth

Even with a perfect normal map, a poorly placed light wipes out the illusion:

- **Light from directly in front** → all normals face the same direction as the
  light, uniform brightness, no depth cues.
- **Light from behind** → the object is uniformly dark.
- **Light from the side at ~30–60 °** → normals tilted toward the light are bright,
  normals tilted away are dark, creating **strong highlight-to-shadow gradients**
  that the human visual system reads as three-dimensional form.

The scene uses a warm directional light at **Transform rotation X: 50°, Y: -30°**
(Unity Euler angles on the `DirectionalLight` GameObject's Transform component —
X tilts the light from overhead toward the horizon; Y rotates it horizontally,
placing it to the left of the scene).  This angle:

1. Produces a broad highlight on the top-facing surfaces (cup rim, ship deck).
2. Creates a shadow in recessed areas (cup interior, glasses lens frame).
3. Leaves a soft ambient fill from `unity_AmbientSky` so shadow areas are not
   pure black.

The ambient + diffuse formula in the shader is:

```hlsl
fixed3 finalRGB = albedo.rgb * (unity_AmbientSky.rgb + _LightColor0.rgb * NdotL);
```

The ambient term prevents the dark side of each sprite from going fully black,
which would look unnatural and reveal the flat geometry.

---

### How the three pillars combine

```
Normal map  →  per-pixel lighting variation  →  perceived bumps & depth
Billboard   →  camera always sees front face  →  no thin-edge give-away
Light angle →  strong highlight/shadow ratio  →  reinforces perceived form
```

Each pillar is necessary but not sufficient on its own:

- Normal map alone on a static quad: depth disappears as soon as you look from an
  angle and see the thin edge.
- Billboard alone (no normal map): sprite brightens and darkens uniformly, reads
  as flat immediately.
- Good light alone: highlights the flatness more than it hides it without a
  normal map to vary the surface orientation.

Together they fool the visual system into perceiving volume where there is none.

---

### Limitations

| Limitation | Description |
|------------|-------------|
| **Silhouette** | The outline of the quad remains rectangular.  Objects with complex outlines should use an alpha-cut texture; the shader discards pixels with `alpha < 0.01`. |
| **Single light** | The custom BiRP shader only handles one directional light.  Additional lights require extra passes or a URP-lit approach. |
| **No self-shadowing** | The sprite cannot cast a shadow from one part of itself onto another.  Pre-baked ambient occlusion in the albedo texture partially compensates for this. |
| **Parallax break** | Moving the camera to a very shallow angle reveals the flat surface despite billboarding. `CameraController` clamps the pitch above 10 ° to hide this. |

---

### Extensions

- **Specular / gloss map** — add a fourth texture channel encoding surface
  shininess; compute Blinn-Phong highlight in the fragment shader for metallic
  or wet-surface looks.
- **Parallax occlusion mapping (POM)** — offset the UV lookup based on the
  view direction, simulating geometric depth even on a flat surface.
- **Point lights** — replace the directional light with a desk lamp point light;
  the normal map will make the sprite appear to be lit from a local source.
- **Rim lighting** — add a fresnel term to brighten the edges of the sprite,
  enhancing the silhouette and further reinforcing perceived volume.

---

## Requirements

- Unity 2022 LTS or newer (URP or Built-in Render Pipeline).
- Sprite textures + matching **normal maps** for each prop.
  - Normal maps must be imported with **Texture Type = Normal map** in the Inspector.
  - Tools like [NormalMap Online](https://cpetry.github.io/NormalMap-Online/) can
    generate a normal map from any height or colour image in seconds.

---

## Quick-start

### 1. Create the scene

1. Open Unity and create a new **3-D** (Built-in RP) or **URP 3-D** project.
2. Copy the `Assets/` folder from this repository into your project's `Assets/` folder.
3. Create a new scene (File → New Scene).

### 2. Create the material (Built-in RP)

1. **Assets → Create → Material** — name it `SpriteLitNormalMapMat`.
2. In the **Shader** dropdown choose **Custom/SpriteLitNormalMap**.
3. Leave textures empty for now (they are assigned per-object at runtime).

> **URP users**: instead create a material with the built-in
> `Universal Render Pipeline/2D/Sprite-Lit-Default` shader.
> Assign your normal map under *Additional Maps → Normal Map* — the custom shader
> is not needed.

### 3. Set up DeskSceneManager

1. Create an empty **GameObject** in the scene, name it `SceneManager`.
2. Add the **DeskSceneManager** component.
3. Fill in the Inspector fields:
   | Field | Value |
   |-------|-------|
   | Map Texture | Your map/blueprint image |
   | Desk Material | Any standard grey/wood material |
   | Map Material | Any standard material with the map texture |
   | Sprite Lit Material | `SpriteLitNormalMapMat` (created above) |
   | Glasses Albedo / Normal | Your glasses sprite + its normal map |
   | Coffee Cup Albedo / Normal | Your coffee-cup sprite + its normal map |
   | Ship Albedo / Normal | Your ship miniature sprite + its normal map |

### 4. Set up the camera

1. Select your **Main Camera**.
2. Add the **CameraController** component.
3. Adjust `cameraStartPosition` (e.g. `0, 3, -4`) and `cameraStartEuler` (`35, 0, 0`)
   so the camera looks down at the desk from a comfortable angle.

### 5. Add a Directional Light

If your scene doesn't already have one:
- **GameObject → Light → Directional Light**
- Set rotation to roughly **X: 50, Y: -30** (top-left at 45 °).
- This angle gives the best normal-map contrast on the sprites.

### 6. Play

Press **Play** — the scene is built procedurally by `DeskSceneManager.BuildScene()`.
You should see the desk, the flat map and three billboard props lit with apparent depth.

---

## Camera Controls (at runtime)

| Input | Action |
|-------|--------|
| **W / A / S / D** or **Arrow keys** | Translate camera on X and Z axis |
| **Scroll wheel** | Zoom in / out |
| **Right mouse + drag** | Orbit / rotate view |
| **Middle mouse + drag** | Pan (translate without rotating) |

---

## Customising Props

Each prop is a standard Unity **Quad** with two MonoBehaviour components:

- **SpriteBillboard** — controls how the quad rotates to face the camera.
  - `Full` — full spherical billboard (ship miniature).
  - `AxisY` — stays upright, rotates only on Y (glasses, coffee cup).
- **NormalMappedSprite** — assigns the material and per-object textures.
  - `normalStrength` — raise above 1 for an exaggerated 3-D look.

You can add more props by calling `DeskSceneManager.CreatePropQuad(...)` or by
duplicating an existing quad and changing the texture references on its
`NormalMappedSprite` component.

---

## Shader Details

`Assets/Shaders/SpriteLitNormalMap.shader` is a Built-in RP forward-base pass
that:

1. Samples the albedo and normal map.
2. Unpacks the normal and scales its XY by `_NormalStrength`.
3. Transforms the tangent-space normal into world space using the TBN matrix.
4. Computes Lambertian diffuse from `_LightColor0` + ambient from `unity_AmbientSky`.
5. Outputs `RGB * (ambient + diffuse)` with the original alpha (transparent edges
   are discarded via `clip(alpha - 0.01)`).
6. Renders with `Cull Off` so the billboard is visible from both sides.

---

## Tips

- **Normal map generation**: free tools like [NormalMap Online](https://cpetry.github.io/NormalMap-Online/)
  or Photoshop's *3D → Generate Normal Map* can create a normal map from any sprite.
- **Parallax enhancement**: for extra depth perception, offset the normal-map UV
  slightly based on the camera's view direction (parallax occlusion mapping) —
  an advanced extension of this technique.
- **Shadow casting**: enable **Cast Shadows** on the Quad's MeshRenderer and add a
  shadow-receiving plane under the props for extra realism.
- **Sprite sheets**: if your props use sprite-sheet animations, tile the UV in the
  shader by adjusting `_MainTex_ST` each frame to pick the correct cell.
