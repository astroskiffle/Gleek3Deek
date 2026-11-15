import numpy as np

from analysis import cavity_per_vertex
from environment import ENV_DEFAULTS, clean_env, env_shader_code


def fold(sign, n=21):
    """A strip folded along x = 0 (z = sign*|x|), seen from +z. sign +1 is a valley, -1 a ridge."""
    xs = np.linspace(-1, 1, n)
    ys = np.linspace(0, 1, 5)
    P = np.array([[x, y, sign * abs(x)] for y in ys for x in xs])
    T = []
    for j in range(len(ys) - 1):
        for i in range(n - 1):
            a, b = j * n + i, j * n + i + 1
            c, d = (j + 1) * n + i, (j + 1) * n + i + 1
            T += [[a, b, d], [a, d, c]]
    return P, np.array(T)


def test_valley_is_dark_ridge_and_flat_are_not():
    P, T = fold(+1)
    c = cavity_per_vertex(P, T)
    mid = np.isclose(P[:, 0], 0.0) & (P[:, 1] > 0.2) & (P[:, 1] < 0.8)
    far = np.abs(P[:, 0]) > 0.5
    assert c[mid].min() > 0.2 and c[far].max() < 0.05
    r = cavity_per_vertex(*fold(-1))
    assert r.max() < 0.05


def test_flat_and_empty_inputs():
    P, T = fold(+1)
    P[:, 2] = 0.0
    assert cavity_per_vertex(P, T).max() < 1e-6
    assert len(cavity_per_vertex(np.zeros((0, 3)), np.zeros((0, 3), int))) == 0
    c = cavity_per_vertex(*fold(+1))
    assert c.dtype == np.float32 and c.min() >= 0.0 and c.max() <= 1.0


def test_shader_uses_attribute_only_when_asked():
    env = clean_env({"enabled": True, "fake_ao": True, "ao_strength": 0.5})
    assert env["fake_ao"] is True and env["ao_strength"] == 0.5
    off = env_shader_code(env, (0, 0, 1))
    on = env_shader_code(env, (0, 0, 1), ao=True)
    assert "gkAOv" not in off and "envAO" not in off
    assert "gkAOv" in on and "0.5000" in on and "envAmb *= envAO" in on
    assert on.index("envAmb *= envAO") < on.index("envNL")


def test_defaults_are_off_and_clamped():
    assert ENV_DEFAULTS["fake_ao"] is False
    assert clean_env({"ao_strength": 9})["ao_strength"] == 1.0


# ----- panorama irradiance -----
def test_sh_constant_sky_gives_that_colour_everywhere():
    from environment import sh_eval, sh_irradiance
    disp = np.full((32, 64, 3), 0.0, np.float32)
    disp[...] = [0.2, 0.5, 0.8]
    k = sh_irradiance(disp)
    for n in ([0, 1, 0], [0, -1, 0], [1, 0, 0], [0.6, 0.0, 0.8]):
        assert np.allclose(sh_eval(k, n), [0.2, 0.5, 0.8], atol=0.02)


def test_sh_bright_top_lights_up_facing_normals_more():
    from environment import sh_eval, sh_irradiance
    disp = np.zeros((32, 64, 3), np.float32)
    disp[:16] = 1.0                                   # top half of the panorama bright
    k = sh_irradiance(disp)
    assert sh_eval(k, [0, 1, 0]).mean() > 0.8 > 0.2 > sh_eval(k, [0, -1, 0]).mean()
    assert abs(sh_eval(k, [1, 0, 0]).mean() - 0.5) < 0.1


def test_sh_follows_a_bright_patch_in_x():
    from environment import equirect_dir, sh_eval, sh_irradiance
    disp = np.zeros((32, 64, 3), np.float32)
    u, v = np.meshgrid((np.arange(64) + 0.5) / 64, 1 - (np.arange(32) + 0.5) / 32)
    disp[(equirect_dir(u, v) @ np.array([1.0, 0, 0])) > 0.7] = 1.0
    k = sh_irradiance(disp)
    assert sh_eval(k, [1, 0, 0]).mean() > sh_eval(k, [-1, 0, 0]).mean() + 0.2


def test_pano_frame_matrix_rotates_with_up_and_yaw():
    from environment import pano_frame_matrix
    assert np.allclose(pano_frame_matrix("Y", 0.0), np.eye(3))
    z = pano_frame_matrix("Z", 0.0)                   # world Z (up) must become frame Y
    assert np.allclose(z @ [0, 0, 1], [0, 1, 0])
    m = pano_frame_matrix("Y", 90.0)
    assert np.allclose(np.linalg.det(m), 1.0) and not np.allclose(m, np.eye(3))


def test_shader_gets_irradiance_only_when_asked():
    from environment import pano_frame_matrix, sh_irradiance
    k = sh_irradiance(np.full((8, 16, 3), 0.5, np.float32))
    sh = (k, pano_frame_matrix("Y", 0.0))
    env = clean_env({"enabled": True, "pano_light": 0.7})
    assert "envIrr" not in env_shader_code(env, (0, 0, 1))
    assert "envIrr" not in env_shader_code(clean_env({"pano_light": 0.0}), (0, 0, 1), sh=sh)
    assert "envIrr" not in env_shader_code(env, (0, 0, 1), view_locked=True, sh=sh)
    code = env_shader_code(env, (0, 0, 1), sh=sh)
    assert "envIrr" in code and "0.7000" in code and "lightDirectionVC2" in code
    assert "cross(envAxZ, envAxX)" in env_shader_code(env, (0, 0, 1), sh=sh, up_axis="Z")
