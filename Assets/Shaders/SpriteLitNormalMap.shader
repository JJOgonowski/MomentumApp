// SpriteLitNormalMap.shader
//
// A hand-written HLSL shader for Unity's Built-in Render Pipeline (BiRP) that
// renders a transparent sprite quad with:
//   • Albedo / colour texture (_MainTex)
//   • Normal map               (_NormalMap)   — import texture as "Normal map" in Unity
//   • Adjustable normal strength (_NormalStrength)
//   • Single directional light contribution  (_WorldSpaceLightPos0 / _LightColor0)
//   • Ambient light             (unity_AmbientSky)
//   • Alpha cutout              (alpha < 0.01 discarded)
//
// URP users: use "Universal Render Pipeline/2D/Sprite-Lit-Default" instead and set
// _NormalMap as a secondary texture — no custom shader needed.
//
// Usage
// -----
// 1. Create a new Material: Assets > Create > Material.
// 2. In the shader dropdown select "Custom/SpriteLitNormalMap".
// 3. Assign your albedo texture to "_MainTex" and your normal map to "_NormalMap".
// 4. Adjust _NormalStrength (1 = realistic, 2 = exaggerated).
// 5. Assign this material to the spriteLitMaterial field on DeskSceneManager.
//
Shader "Custom/SpriteLitNormalMap"
{
    Properties
    {
        _MainTex        ("Albedo (RGB) Alpha (A)",  2D)     = "white" {}
        _NormalMap      ("Normal Map",              2D)     = "bump"  {}
        _NormalStrength ("Normal Strength",         Range(0,4)) = 1.0
        _Color          ("Tint",                    Color)  = (1,1,1,1)
    }

    SubShader
    {
        Tags
        {
            "Queue"           = "Transparent"
            "RenderType"      = "Transparent"
            "IgnoreProjector" = "True"
        }

        // -----------------------------------------------------------------
        // Pass 1 — lit pass (single directional light + ambient)
        // -----------------------------------------------------------------
        Pass
        {
            Name "LitPass"
            Tags { "LightMode" = "ForwardBase" }

            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Off           // render both sides so the billboard is visible
                               // from any angle

            CGPROGRAM
            #pragma vertex   vert
            #pragma fragment frag
            #pragma multi_compile_fwdbase
            #include "UnityCG.cginc"
            #include "Lighting.cginc"

            // ---- Uniforms ----
            sampler2D _MainTex;
            float4    _MainTex_ST;
            sampler2D _NormalMap;
            float4    _NormalMap_ST;
            float     _NormalStrength;
            fixed4    _Color;

            // ---- Vertex input / output ----
            struct appdata
            {
                float4 vertex  : POSITION;
                float3 normal  : NORMAL;
                float4 tangent : TANGENT;
                float2 uv      : TEXCOORD0;
            };

            struct v2f
            {
                float4 pos    : SV_POSITION;
                float2 uv     : TEXCOORD0;
                float2 uvNorm : TEXCOORD1;
                // TBN matrix columns in world space
                float3 worldTangent  : TEXCOORD2;
                float3 worldBitang   : TEXCOORD3;
                float3 worldNormal   : TEXCOORD4;
            };

            // ---- Vertex shader ----
            v2f vert(appdata v)
            {
                v2f o;
                o.pos      = UnityObjectToClipPos(v.vertex);
                o.uv       = TRANSFORM_TEX(v.uv, _MainTex);
                o.uvNorm   = TRANSFORM_TEX(v.uv, _NormalMap);

                // Build TBN (tangent-bitangent-normal) in world space so we
                // can transform the normal-map sample into world space for lighting.
                float3 worldNormal  = UnityObjectToWorldNormal(v.normal);
                float3 worldTangent = UnityObjectToWorldDir(v.tangent.xyz);
                float  sign         = v.tangent.w * unity_WorldTransformParams.w;
                float3 worldBitang  = cross(worldNormal, worldTangent) * sign;

                o.worldNormal  = worldNormal;
                o.worldTangent = worldTangent;
                o.worldBitang  = worldBitang;
                return o;
            }

            // ---- Fragment shader ----
            fixed4 frag(v2f i) : SV_Target
            {
                // Sample albedo
                fixed4 albedo = tex2D(_MainTex, i.uv) * _Color;

                // Discard fully transparent pixels (clean sprite edges)
                clip(albedo.a - 0.01);

                // Sample normal map and unpack to [-1,1]
                float3 tangentNormal = UnpackNormal(tex2D(_NormalMap, i.uvNorm));

                // Apply normal strength (lerp towards flat [0,0,1] when strength < 1)
                tangentNormal.xy *= _NormalStrength;
                tangentNormal      = normalize(tangentNormal);

                // Convert to world space using the TBN matrix
                float3x3 tbn         = float3x3(
                    normalize(i.worldTangent),
                    normalize(i.worldBitang),
                    normalize(i.worldNormal));
                float3 worldNormal   = normalize(mul(tangentNormal, tbn));

                // Directional light
                float3 lightDir      = normalize(_WorldSpaceLightPos0.xyz);
                float  NdotL         = max(0.0, dot(worldNormal, lightDir));
                float3 diffuse       = _LightColor0.rgb * NdotL;

                // Ambient
                float3 ambient       = unity_AmbientSky.rgb;

                // Final colour
                fixed3 finalRGB = albedo.rgb * (ambient + diffuse);
                return fixed4(finalRGB, albedo.a);
            }
            ENDCG
        }
    }

    FallBack "Transparent/Diffuse"
}
