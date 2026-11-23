import numpy as np
import pytest

import environment
import formats
from environment import (ENV_DEFAULTS, clean_env, env_shader_code, sh_eval, sh_gloss, sh_irradiance, sh_radiance)


def sky(h=32, w=64, top=(0.9, 0.9, 1.0), bottom=(0.2, 0.15, 0.1)):
    """A panorama that is light at the top and dark at the bottom."""
    t = np.linspace(1, 0, h)[:, None, None]
    img = np.array(top) * t + np.array(bottom) * (1 - t)
    return np.repeat(img, w, axis=1).astype(np.float32)


def test_option_defaults_off_and_survives_cleaning():
    assert ENV_DEFAULTS["pbr"] is False
    assert clean_env({"pbr": True})["pbr"] is True
    assert clean_env({})["pbr"] is False


def test_radiance_of_a_flat_sky_is_that_colour_everywhere():
    flat = np.full((32, 64, 3), (0.6, 0.4, 0.2), np.float32)
    k = sh_radiance(flat)
    for n in ((0, 1, 0), (1, 0, 0), (0.6, 0.0, 0.8), (0, -1, 0)):
        assert np.allclose(sh_eval(k, n), (0.6, 0.4, 0.2), atol=0.03)


def test_radiance_sees_the_light_above_and_the_dark_below():
    k = sh_radiance(sky())
    up, down = sh_eval(k, (0, 1, 0)), sh_eval(k, (0, -1, 0))
    assert up.mean() > down.mean() + 0.3


def test_gloss_blurs_but_keeps_the_average_colour():
    k = sh_radiance(sky())
    assert np.allclose(sh_gloss(k, 0.0), k)
    soft = sh_gloss(k, 1.0)
    assert np.allclose(soft[0], k[0])                              # the average is untouched
    assert np.all(np.abs(soft[4:]) <= np.abs(k[4:]) + 1e-12)       # detail is removed
    # the contrast between up and down shrinks as the surface gets rougher
    spread = [np.ptp([sh_eval(sh_gloss(k, r), n).mean() for n in ((0, 1, 0), (0, -1, 0))])
              for r in (0.0, 0.5, 1.0)]
    assert spread[0] > spread[1] > spread[2]


def test_fully_rough_reflection_is_close_to_diffuse_light():
    disp = sky()
    n = (0.3, 0.9, 0.3)
    n = np.array(n) / np.linalg.norm(n)
    rough = sh_eval(sh_gloss(sh_radiance(disp), 1.0), n).mean()
    diffuse = sh_eval(sh_irradiance(disp), n).mean()
    assert abs(rough - diffuse) < 0.12


ENV = clean_env({"pbr": True, "highlight": 0.25})
SHC = (sh_irradiance(sky()), np.eye(3), sh_radiance(sky()))


def code(**kw):
    kw.setdefault("pbr", (0.0, 0.5))
    return env_shader_code(kw.pop("env", ENV), (0, 0, 1), **kw)


def test_classic_shader_is_unchanged_when_pbr_is_off_or_has_no_material():
    off = env_shader_code(clean_env({}), (0, 0, 1), pbr=(1.0, 0.1))
    none = env_shader_code(ENV, (0, 0, 1))
    for c in (off, none):
        assert "envF0" not in c and "envRough" not in c and "envSpec = pow" in c


def test_pbr_shader_has_ggx_fresnel_and_the_material_values():
    c = code(pbr=(0.8, 0.3))
    assert "envF0" in c and "reflect(" in c and "envD =" in c and "pow(1.0 - envVH, 5.0)" in c
    assert "envRough = 0.3000" in c and "envMetal = 0.8000" in c
    assert "envSpec = pow" not in c


def test_roughness_is_never_exactly_zero():
    assert "envRough = 0.0600" in code(pbr=(1.0, 0.0))
    assert "envMetal = 1.0000" in code(pbr=(5.0, 0.5))               # out-of-range values are clamped


def test_reflection_comes_from_the_panorama_when_there_is_one():
    c = code(sh=SHC)
    assert "envRF" in c and "envAxX" in c and "envRh" not in c
    plain = code()
    assert "envRh" in plain and "envRF" not in plain and "envAxX" not in plain


def test_panorama_reflection_works_with_the_diffuse_light_slider_at_zero():
    c = code(sh=SHC)                                                # pano_light is 0 in ENV
    assert "envRF" in c and "envIrr" not in c
    lit = code(env=clean_env({"pbr": True, "pano_light": 0.7}), sh=SHC)
    assert "envIrr" in lit and "envRF" in lit


def test_view_locked_fallback_has_no_panorama_maths():
    c = code(sh=SHC, view_locked=True)
    assert "envAxX" not in c and "envRh" in c


def test_blurrier_material_changes_the_coefficients_in_the_code():
    assert code(sh=SHC, pbr=(0.0, 0.1)) != code(sh=SHC, pbr=(0.0, 0.9))


def test_ambient_occlusion_also_darkens_the_reflection():
    c = code(ao=True)
    assert "envSpecAO = envAO;" in c
    assert c.index("envSpecAO = envAO;") < c.index("envSpecAmb")
    assert "envSpecAO = envAO" not in code()


def test_up_axis_z_builds_the_other_frame():
    assert "cross(envAxZ, envAxX)" in code(sh=SHC, up_axis="Z")


def test_every_variable_is_declared_before_it_is_used():
    import re
    c = code(sh=SHC, ao=True)
    declared = set()
    for line in c.split("\n"):
        m = re.match(r"\s*(?:float|vec2|vec3|vec4)\s+(env\w+)", line)
        rhs = line.split("=", 1)[1] if "=" in line else ""
        for used in re.findall(r"\benv[A-Za-z0-9]+\b", rhs):
            assert used in declared or used == (m.group(1) if m else None), (used, line)
        if m:
            declared.add(m.group(1))


class FakeProp:
    def __init__(self, metal, rough, tex=None):
        self.m, self.r, self.tex = metal, rough, tex

    def GetMetallic(self): return self.m
    def GetRoughness(self): return self.r
    def GetTexture(self, name): return self.tex if name == "materialTex" else None


def test_factors_without_a_map_are_used_as_they_are():
    assert formats.pbr_factors(FakeProp(0.3, 0.7)) == pytest.approx((0.3, 0.7))
    assert formats.pbr_factors(FakeProp(2.0, -1.0)) == (1.0, 0.0)


def test_factors_with_a_map_use_the_map_average(monkeypatch):
    pix = np.zeros((100, 3), np.uint8)
    pix[:, 1] = 128        # roughness ~0.5
    pix[:, 2] = 51         # metallic 0.2

    class Img:
        def GetPointData(self): return self
        def GetScalars(self): return pix
    class Tex:
        def GetInput(self): return Img()
    monkeypatch.setattr(formats.numpy_support, "vtk_to_numpy", lambda a: a, raising=False)
    m, r = formats.pbr_factors(FakeProp(1.0, 1.0, Tex()))
    assert m == pytest.approx(0.2, abs=0.01) and r == pytest.approx(0.502, abs=0.01)


def test_an_unreadable_map_falls_back_to_a_matte_non_metal():
    class Tex:
        def GetInput(self): raise RuntimeError("no image")
    assert formats.pbr_factors(FakeProp(1.0, 1.0, Tex())) == (0.0, 0.6)


def test_a_property_without_pbr_values_gives_none():
    class Bare:
        pass
    assert formats.pbr_factors(Bare()) is None


def test_reflection_gain_is_fixed_and_there_is_no_slider():
    from environment import ENV_SLIDERS, PBR_REFLECTION_GAIN
    assert f"* (envSpecAO * {PBR_REFLECTION_GAIN:.4f})" in code()
    assert "reflect" not in ENV_DEFAULTS and all(k != "reflect" for k, *_ in ENV_SLIDERS)
    assert 1.2 <= PBR_REFLECTION_GAIN <= 2.5


def test_reflection_gains_are_fixed_and_split_white_from_tinted():
    from environment import PBR_METAL_TINT_GAIN, PBR_REFLECTION_GAIN
    assert (PBR_REFLECTION_GAIN, PBR_METAL_TINT_GAIN) == (1.8, 1.2)
    c = code(sh=SHC, pbr=(1.0, 0.4))
    assert "envWhiteRefl * (envSpecAO * 1.8000)" in c and "envTintRefl * (envSpecAO * 1.2000)" in c
    assert not any(k.startswith("dbg_") for k in ENV_DEFAULTS)


def test_surface_mode_combines_the_two_saved_flags():
    from environment import ENV_CHECKBOX_KEYS, set_surface_mode, surface_mode
    e = clean_env({})
    for mode, lighting, pbr in (("off", False, False), ("standard", True, False), ("pbr", True, True)):
        set_surface_mode(e, mode)
        assert (e["lighting"], e["pbr"]) == (lighting, pbr) and surface_mode(e) == mode
    assert surface_mode({"lighting": False, "pbr": True}) == "off"       # PBR means nothing without lighting
    assert surface_mode(clean_env({})) == "standard" or surface_mode(clean_env({})) == "off"
    assert "lighting" not in ENV_CHECKBOX_KEYS and "pbr" not in ENV_CHECKBOX_KEYS and "fake_ao" in ENV_CHECKBOX_KEYS
    assert clean_env({"lighting": False, "pbr": True})["pbr"] is True      # saved settings keep both flags
