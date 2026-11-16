// RetroGleek - screen effect sets: custom presets and the automatic choice for each computer
// Copyright (c) 2026 Mark Billson. MIT License (see LICENSE). Part of RetroGleek; see Program.cs for the overview.

using System;
using System.Collections.Generic;
using System.Globalization;

// One combination of the viewer's screen effects (display only; see Canvas.cs).
//   Scan   0 off, 1 light, 2 medium, 3 strong
//   Mask   0 off, 1 aperture grille, 2 slot mask, 3 dot mask
//   Signal 0 RGB, 1 S-Video, 2 composite
//   Glow   0 off, 1 soft, 2 strong
//   Curve  0 flat, 1 slight, 2 strong curvature (automatic mode keeps your own)
sealed class EffectSet
{
    public string Name;              // preset name, or (automatic choice) the screen it imitates
    public bool Tv;
    public int Scan, Mask, Signal, Glow, Curve;

    public EffectSet Copy()
    {
        return new EffectSet { Name = Name, Tv = Tv, Scan = Scan, Mask = Mask, Signal = Signal, Glow = Glow, Curve = Curve };
    }

    public bool SameAs(EffectSet o)
    {
        return o != null && Tv == o.Tv && Scan == o.Scan && Mask == o.Mask && Signal == o.Signal && Glow == o.Glow && Curve == o.Curve;
    }

    static readonly string[] ScanText = { "no scanlines", "light scanlines", "medium scanlines", "strong scanlines" };
    static readonly string[] MaskText = { "no mask", "aperture grille", "slot mask", "dot mask" };
    static readonly string[] SignalText = { "RGB", "S-Video", "composite" };
    static readonly string[] GlowText = { "no glow", "soft glow", "strong glow" };
    static readonly string[] CurveText = { "", ", slightly curved", ", strongly curved" };

    // e.g. "S-Video, slot mask, medium scanlines, soft glow, TV aspect"
    public string Describe()
    {
        return SignalText[Signal] + ", " + MaskText[Mask] + ", " + ScanText[Scan] + ", " + GlowText[Glow] + CurveText[Curve] + (Tv ? ", TV aspect" : "");
    }

    // settings.ini: "presetN=tv,scan,mask,signal,glow,curve|name" (presets saved before curvature have 5 numbers)
    public string Serialize()
    {
        string name = (Name ?? "").Replace("|", "/").Trim();
        return (Tv ? "1" : "0") + "," + Scan.ToString(CultureInfo.InvariantCulture) + "," + Mask.ToString(CultureInfo.InvariantCulture) + ","
             + Signal.ToString(CultureInfo.InvariantCulture) + "," + Glow.ToString(CultureInfo.InvariantCulture) + ","
             + Curve.ToString(CultureInfo.InvariantCulture) + "|" + name;
    }

    // null if the text is not a valid preset
    public static EffectSet Parse(string s)
    {
        if (string.IsNullOrEmpty(s)) return null;
        int bar = s.IndexOf('|');
        if (bar < 0) return null;
        string[] v = s.Substring(0, bar).Split(',');
        string name = s.Substring(bar + 1).Trim();
        if ((v.Length != 5 && v.Length != 6) || name.Length == 0) return null;
        int[] n = new int[6];
        for (int i = 0; i < v.Length; i++)
            if (!int.TryParse(v[i], NumberStyles.Integer, CultureInfo.InvariantCulture, out n[i])) return null;
        return new EffectSet
        {
            Name = name, Tv = n[0] != 0,
            Scan = Clamp(n[1], 3), Mask = Clamp(n[2], 3), Signal = Clamp(n[3], 2), Glow = Clamp(n[4], 2), Curve = Clamp(n[5], 2)
        };
    }

    static int Clamp(int v, int max) { return Math.Max(0, Math.Min(max, v)); }

    static EffectSet Make(string screen, int signal, int mask, int scan, int glow)
    {
        return new EffectSet { Name = screen, Tv = true, Signal = signal, Mask = mask, Scan = scan, Glow = glow };
    }

    // ---- automatic mode: the screen and cable a picture from this computer was most often seen on.
    // platform = RECOIL's platform name; origW / origH = the picture's original resolution (0 if not known).
    // These are typical set-ups, not the only ones: many machines could be used with more than one kind of screen.
    // Pixel shape (True TV aspect) is always on. Returns null for pictures that are not retro (no platform).
    public static EffectSet ForPlatform(string platform, int origW, int origH)
    {
        if (string.IsNullOrEmpty(platform)) return null;
        const int RGB = 0, SVIDEO = 1, COMPOSITE = 2;
        const int NOMASK = 0, GRILLE = 1, SLOT = 2, DOT = 3;
        switch (platform)
        {
            // Commodore: the 1701 / 1702 / 1084 monitors took brightness and colour separately (S-Video)
            case "Commodore 64":
            case "Commodore 128":
                return Make("Commodore 1702 / 1084 monitor, separate luma and chroma", SVIDEO, SLOT, 2, 1);
            case "Commodore VIC-20":
            case "Commodore 16/116/Plus4":
                return Make("home TV through the aerial or composite socket", COMPOSITE, SLOT, 2, 1);

            // Sinclair and clones
            case "ZX Spectrum":
            case "ZX Spectrum ULAplus":
            case "ZX81":
                return Make("home TV through the aerial socket", COMPOSITE, SLOT, 2, 1);
            case "ZX Spectrum Profi":
                return Make("RGB monitor", RGB, SLOT, 2, 1);
            case "ZX Evolution":
                return Make("VGA monitor", RGB, GRILLE, 1, 0);
            case "SAM Coupe":
                return Make("TV through the SCART (RGB) socket", RGB, SLOT, 2, 1);

            // Amiga: the 1084S monitor through the RGB socket; DCTV pictures are composite video by design
            case "Amiga":
            case "Amiga HAM-E":
                return Make("Commodore 1084S monitor, RGB", RGB, SLOT, 1, 1);
            case "Amiga DCTV":
                return Make("composite video (DCTV encodes the picture as a composite signal)", COMPOSITE, SLOT, 1, 1);

            // Atari 16 / 32-bit: SC1224 colour monitor, or the SM124 sharp mono monitor for 640 x 400
            case "Atari ST":
            case "Atari STE":
                if (origH >= 400 && origW >= 640) return Make("Atari SM124 mono monitor (sharp, 71 Hz)", RGB, NOMASK, 0, 1);
                return Make("Atari SC1224 colour monitor, RGB", RGB, DOT, 1, 1);
            case "Atari TT":
            case "Atari Falcon":
                return Make("VGA monitor", RGB, GRILLE, 0, 0);
            case "Atari 8-bit":
                return Make("home TV or monitor, composite", COMPOSITE, SLOT, 2, 1);
            case "Atari 8-bit VBXE":
                return Make("RGB monitor", RGB, GRILLE, 1, 0);

            // Amstrad, Acorn, Oric: their own RGB monitors (or RGB through SCART)
            case "Amstrad CPC":
                return Make("Amstrad CTM644 colour monitor, RGB", RGB, SLOT, 2, 1);
            case "BBC Micro":
                return Make("RGB monitor (such as the Microvitec Cub)", RGB, SLOT, 2, 1);
            case "Oric":
                return Make("TV through the SCART (RGB) socket", RGB, SLOT, 2, 1);

            // MSX: MSX1 mostly on a TV; MSX2 and later usually through RGB (SCART)
            case "MSX":
                return Make("home TV, composite", COMPOSITE, SLOT, 2, 1);
            case "MSX2":
            case "MSX2+":
            case "MSX V9990 VDP":
                return Make("TV or monitor through RGB (SCART)", RGB, SLOT, 2, 1);

            // Apple
            case "Apple II":
            case "Apple IIe":
                return Make("composite colour monitor", COMPOSITE, SLOT, 2, 1);
            case "Apple IIGS":
                return Make("AppleColor RGB monitor (Trinitron)", RGB, GRILLE, 1, 1);
            case "Apple Macintosh":
                return Make("built-in sharp mono screen", RGB, NOMASK, 1, 1);

            // PCs and Japanese computers: RGB monitors; 400-line and VGA modes show no visible scanlines
            case "PC":
                return Make("PC colour monitor", RGB, DOT, origH > 0 && origH <= 200 ? 1 : 0, 0);
            case "Tandy 1000":
                return Make("Tandy CGA-style colour monitor", RGB, DOT, 2, 0);
            case "NEC PC-80":
            case "NEC PC-88":
            case "NEC PC-88 VA":
            case "NEC PC-98":
            case "Sharp X68000":
            case "FM Towns":
                return Make("Japanese RGB monitor", RGB, GRILLE, origH >= 400 ? 0 : 1, 0);

            // Soviet computers: usually a home TV
            case "Electronika BK":
            case "Vector-06C":
                return Make("home TV", COMPOSITE, SLOT, 2, 1);
            case "Electronika MC 0515":
                return Make("built-in monitor", RGB, SLOT, 1, 0);

            case "PlayStation":
                return Make("home TV, composite", COMPOSITE, SLOT, 1, 1);

            // LCD screens: no CRT effects at all
            case "Atari Portfolio":
            case "HP 48":
            case "Psion Series 3":
                return Make("LCD screen (no CRT effects)", RGB, NOMASK, 0, 0);
        }
        return Make("a typical colour monitor (computer not in RetroGleek's list)", RGB, GRILLE, 1, 0);
    }
}
