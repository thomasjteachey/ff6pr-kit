using System;
using System.Collections.Generic;
using HarmonyLib;
using PrKit;

namespace PrKit.Ff6
{
    // A randomizer's esper level-up bonuses (SNES esper byte 10: 0-16, 0xFF none; tools/seed_info.py
    // esper_bonus: vanilla's and the seed's by PR magicite content id). The PR builds its bonuses in code
    // (Serial.FF6.Management.MagicStoneData: type, value, text by magicite content id), so an esper whose
    // bonus changed answers as a vanilla esper with that bonus does (its "donor"). Two codes no vanilla
    // esper has: Speed +2 (Speed +1's, doubled; the PR has its text) and HP +100% (HP +10%'s, x10; text of
    // our own). No bonus: an esper without one. Written for Worlds Collide (WcEspers, -ebs/-ebr), in the kit
    // since 2026-11-20 for Beyond Chaos (its `e`).
    public static class SnesEsperBonus
    {
        public static Func<IReadOnlyDictionary<int, int>> Seed = () => null;      // the seed's codes where they differ
        public static Func<IReadOnlyDictionary<int, int>> Vanilla = () => null;   // vanilla's codes, every esper
        public static Action<string, string> SetText = (key, text) => GameText.Set(key, text);
        public static string Tag = "[kit]";
        public static string LastBonus = "";
        static bool busy;

        const int Hp10 = 0, Hp100 = 6, Speed1 = 11, Speed2 = 12, None = 0xFF;

        public static void Patch(Harmony h)
        {
            var t = typeof(Serial.FF6.Management.MagicStoneData);
            int n = 0;
            foreach (var (name, post) in new[] { ("GetParameterType", nameof(Type_Postfix)), ("GetParameterValue", nameof(Value_Postfix)),
                                                 ("GetBonusBaseValue", nameof(Base_Postfix)), ("GetMagicBonusMessageId", nameof(Message_Postfix)) })
            {
                var m = AccessTools.Method(t, name);
                if (m == null) continue;
                h.Patch(m, postfix: new HarmonyMethod(typeof(SnesEsperBonus), post));
                n++;
            }
            Kit.Info($"{Tag} esper bonuses: {n} of 4 lookups hooked");
        }

        // (donor content id, scale) for an esper whose bonus the seed changed; null = the PR's own
        public static (int Donor, int Scale, int Code)? Donor(int contentId)
        {
            var seed = Seed();
            var vanilla = Vanilla();
            if (seed == null || vanilla == null || seed.Count == 0 || !seed.TryGetValue(contentId, out int code)) return null;
            int scale = 1, want = code;
            bool HasCode(int c) { foreach (var v in vanilla.Values) if (v == c) return true; return false; }
            if (code == Speed2 && !HasCode(Speed2)) { want = Speed1; scale = 2; }
            else if (code == Hp100 && !HasCode(Hp100)) { want = Hp10; scale = 10; }
            else if (code > 16) want = None;
            foreach (var kv in vanilla)
                if (kv.Value == want) return (kv.Key, scale, code);
            return null;
        }

        public static void Type_Postfix(Serial.FF6.Management.MagicStoneData __instance, int contentId, ref Last.Defaine.ParameterType __result)
        {
            if (busy) return;
            var d = Donor(contentId);
            if (d == null) return;
            busy = true;
            try { __result = __instance.GetParameterType(d.Value.Donor); }
            catch (Exception e) { Hooks.WarnOnce("esper-type", e); }
            finally { busy = false; }
        }

        public static void Value_Postfix(Serial.FF6.Management.MagicStoneData __instance, int contentId, int value, ref int __result)
        {
            if (busy) return;
            var d = Donor(contentId);
            if (d == null) return;
            busy = true;
            try
            {
                __result = __instance.GetParameterValue(d.Value.Donor, value) * d.Value.Scale;
                LastBonus = $"esper {contentId}: bonus code {d.Value.Code} as esper {d.Value.Donor}'s x{d.Value.Scale} = {__result} (base {value})";
            }
            catch (Exception e) { Hooks.WarnOnce("esper-value", e); }
            finally { busy = false; }
        }

        public static void Base_Postfix(Serial.FF6.Management.MagicStoneData __instance, int contentId, ref int __result)
        {
            if (busy) return;
            var d = Donor(contentId);
            if (d == null) return;
            busy = true;
            try { __result = __instance.GetBonusBaseValue(d.Value.Donor) * d.Value.Scale; }
            catch (Exception e) { Hooks.WarnOnce("esper-base", e); }
            finally { busy = false; }
        }

        public static void Message_Postfix(Serial.FF6.Management.MagicStoneData __instance, int contentId, ref string __result)
        {
            if (busy) return;
            var d = Donor(contentId);
            if (d == null) return;
            busy = true;
            try
            {
                var key = __instance.GetMagicBonusMessageId(d.Value.Donor);
                if (d.Value.Code == Speed2 && d.Value.Scale == 2)
                    key = key == "MSG_MAG_INF_146" ? "MSG_MAG_INF_166" : key == "MSG_MAG_INF_161" ? "MSG_MAG_INF_167" : key;
                else if (d.Value.Code == Hp100 && d.Value.Scale == 10)
                {
                    bool longText = key == "MSG_MAG_INF_138";
                    key = longText ? "WC_ESPER_HP100" : "WC_ESPER_HP100_SHORT";
                    SetText(key, longText ? "+100% bonus to HP increase at next level-up" : "HP +100%");
                }
                __result = key;
            }
            catch (Exception e) { Hooks.WarnOnce("esper-text", e); }
            finally { busy = false; }
        }
    }
}
