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

## The Technique: Normal-Map Billboards

The "3-D illusion" on flat sprites is achieved by combining three ideas:

| Technique | What it does |
|-----------|--------------|
| **Normal map** | Encodes a per-pixel surface orientation so that light responds as if the surface has bumps, depth and cavities — even on a flat quad. |
| **Billboard** | `SpriteBillboard` rotates the quad every frame so it always faces the camera. The viewer never sees the "paper thin" edge. |
| **Directional light at an angle** | A ~45 ° top-left light creates highlights and cast-shadows that reinforce the perceived depth. |

The result: a flat coffee-cup PNG looks like a real object sitting on a desk.

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
