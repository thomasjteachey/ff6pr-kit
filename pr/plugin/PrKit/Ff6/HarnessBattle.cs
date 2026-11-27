using System;
using System.Collections.Generic;
using System.Linq;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Last.Battle;
using Last.Data.Master;
using Last.Defaine;
using Last.Management;

namespace PrKit.Ff6
{
    // Battle probes over the harness for any FF6 mod (2026-11-25, first for BNW's unclear readme rows): a test sets a
    // battle up and has any fighter act, then reads the result, without menus. A plugin opts in with Register().
    //   units                          every fighter: p0-p3 / e0-eN, name, HP/MaxHP, MP, conditions
    //   unithp <unit> <hp> [mp]         set HP (and MP); 0 HP alone doesn't KO (use cond <unit> +UnableFight)
    //   cond <unit> +<type>|-<type>    add or remove a condition (ConditionType name or number) through the
    //                                  battle's own BattleConditionController (InterruptAdd/RemoveCondition)
    //   act <unit> <command> <ability> <target>   queue an act: a PR command id, a PR ability id (0: the command's
    //                                  own AbilityId), a target unit or allp / alle. A party member's act goes as an
    //                                  interrupting counter, a monster's as a Normal act: BC's finding (BcJunctionActs,
    //                                  bc-selftest-4: a party member's Normal or plain interrupt acts never landed).
    //   endfight                       every enemy dies the game's way (the kit's AI host: SnesAiHost.KillAllForTest)
    //   giveespers [all|<content id>..]   magicite into the inventory (memory only; content type 9), e.g. to see
    //                                  a mod's Magicite list in a test
    // Units: p<n> = the n-th party member (GetPlayerUnits order, dead ones included), e<n> = the n-th monster.
    public static class HarnessBattle
    {
        static bool registered;

        public static void Register()
        {
            if (registered) return;
            registered = true;
            Harness.Register("units", _ => Units(), "units: every fighter in the battle (p0.. party, e0.. monsters): HP, MP, conditions");
            Harness.Register("unithp", UnitHp, "unithp <unit> <hp> [mp]: set a fighter's HP (and MP); units p0.. / e0..");
            Harness.Register("cond", Cond, "cond <unit> +<ConditionType>|-<ConditionType>: add or remove a condition (name or number)");
            Harness.Register("act", Act, "act <unit> <command> <ability|0> <unit|allp|alle> [turn]: queue an act (a party member's as a counter, or with turn as a turn's)");
            // the AI host's test kill (BNW's AiFights has the same): every enemy dies the game's way, so a scripted story
            // fight the kit's enemyhp 1 can't finish (an invincible part, a flee script) still ends (story_bosses.py)
            Harness.Register("endfight", _ => SnesAiHost.KillAllForTest("endfight"), "endfight: every enemy left dies the game's way");
            Harness.Register("giveespers", GiveEspers, "giveespers [all|<content id>..]: magicite into the inventory (memory only)");
        }

        static List<BattleUnitData> Players()
        {
            var l = new List<BattleUnitData>();
            var b = BattlePlugManager.Instance();
            if (b == null || !b.IsBattle()) return l;
            foreach (var u in b.GetPlayerUnits()) if (u != null) l.Add(u);
            return l;
        }

        static List<BattleUnitData> Enemies()
        {
            var l = new List<BattleUnitData>();
            var b = BattlePlugManager.Instance();
            if (b == null || !b.IsBattle()) return l;
            foreach (var u in b.GetEnemyUnits()) if (u != null) l.Add(u);
            return l;
        }

        static BattleUnitData Unit(string s)
        {
            if (string.IsNullOrEmpty(s) || s.Length < 2 || !int.TryParse(s.Substring(1), out int i)) return null;
            var l = s[0] == 'p' ? Players() : s[0] == 'e' ? Enemies() : null;
            return l != null && i >= 0 && i < l.Count ? l[i] : null;
        }

        public static string Name(BattleUnitData u)
        {
            try
            {
                var p = u?.TryCast<BattlePlayerData>();
                if (p != null) return p.ownedCharacterData?.Name ?? "?";
                var e = u?.TryCast<BattleEnemyData>();
                var id = e?.GetMonster()?.Id;
                return id != null ? "monster " + id : "?";
            }
            catch { return "?"; }
        }

        static string Describe(string tag, BattleUnitData u)
        {
            var p = u?.BattleUnitDataInfo?.Parameter;
            if (p == null) return tag + " ?";
            var conds = u.BattleUnitDataInfo.GetConfirmedConditionType();
            var names = new List<string>();
            if (conds != null) foreach (var c in conds) names.Add(c.ToString());
            return $"{tag} {Name(u)} HP {p.CurrentHP}/{p.ConfirmedMaxHp()} MP {p.CurrentMP} [{string.Join(" ", names)}]";
        }

        static string Units()
        {
            var ps = Players();
            if (ps.Count == 0) return "error: not in battle";
            var lines = ps.Select((u, i) => Describe("p" + i, u)).ToList();
            lines.AddRange(Enemies().Select((u, i) => Describe("e" + i, u)));
            return string.Join(" | ", lines);
        }

        static string UnitHp(string[] a)
        {
            var u = a.Length > 1 ? Unit(a[0]) : null;
            if (u == null || !int.TryParse(a[1], out int hp)) return "error: unithp <unit> <hp> [mp]";
            var p = u.BattleUnitDataInfo.Parameter;
            p.CurrentHP = hp;
            if (a.Length > 2 && int.TryParse(a[2], out int mp)) p.CurrentMP = mp;
            return Describe(a[0], u);
        }

        static bool ParseCondition(string s, out ConditionType t)
        {
            if (int.TryParse(s, out int n)) { t = (ConditionType)n; return true; }
            return Enum.TryParse(s, true, out t);
        }

        static string Cond(string[] a)
        {
            var u = a.Length > 1 ? Unit(a[0]) : null;
            if (u == null || a[1].Length < 2 || (a[1][0] != '+' && a[1][0] != '-') || !ParseCondition(a[1].Substring(1), out var t))
                return "error: cond <unit> +<ConditionType>|-<ConditionType>";
            var cc = BattlePlugManager.Instance()?.BattleConditionController;
            if (cc == null) return "error: no condition controller";
            if (a[1][0] == '+') cc.InterruptAddCondition(u, t);
            else cc.InterruptRemoveCondition(u, t);
            return Describe(a[0], u);
        }

        const int MagiciteType = 9;   // content.csv type_id of the 27 espers

        static string GiveEspers(string[] a)
        {
            var udm = UserDataManager.Instance();
            var mm = MasterManager.Instance;
            if (udm?.OwnedMagicStoneList == null || mm == null) return "error: load a save first";
            var want = new HashSet<int>();
            foreach (var s in a) if (int.TryParse(s, out int id)) want.Add(id);
            var items = new OwnedItemClient();
            int n = 0;
            foreach (var ct in mm.GetList<Content>().Values)
            {
                if (ct == null || ct.TypeId != MagiciteType || (want.Count > 0 && !want.Contains(ct.Id))) continue;
                if (udm.OwnedMagicStoneList.Contains(ct.Id)) continue;
                items.AddMagicStone(ct.Id);
                if (!udm.OwnedMagicStoneList.Contains(ct.Id)) udm.OwnedMagicStoneList.Add(ct.Id);
                n++;
            }
            return $"giveespers: {n} added, {udm.OwnedMagicStoneList.Count} owned";
        }

        static string Act(string[] a)
        {
            if (a.Length < 4 || !int.TryParse(a[1], out int command) || !int.TryParse(a[2], out int ability))
                return "error: act <unit> <command> <ability|0> <unit|allp|alle>";
            var who = Unit(a[0]);
            var targets = a[3] == "allp" ? Players() : a[3] == "alle" ? Enemies() : new List<BattleUnitData> { Unit(a[3]) };
            if (who == null || targets.Count == 0 || targets.Any(t => t == null)) return "error: no such unit";
            var bm = BattlePlugManager.Instance();
            var mm = MasterManager.Instance;
            var cmd = mm?.GetData<Command>(command);
            if (bm == null || cmd == null) return $"error: no command {command}";
            var ab = mm.GetData<Ability>(ability > 0 ? ability : cmd.AbilityId);
            if (ab == null) return $"error: no ability {ability}";
            var abilities = new Il2CppSystem.Collections.Generic.List<Ability>();
            abilities.Add(ab);
            var arr = new Il2CppReferenceArray<BattleUnitData>(targets.Count);
            for (int i = 0; i < targets.Count; i++) arr[i] = targets[i];
            bool party = who.TryCast<BattlePlayerData>() != null;
            bool foes = party != (targets[0].TryCast<BattlePlayerData>() != null);
            var tt = targets.Count > 1 ? (foes ? BattleActData.TargetType.AllEnemy : BattleActData.TargetType.AllMember)
                                       : (foes ? BattleActData.TargetType.SingleEnemy : BattleActData.TargetType.SingleMember);
            var act = new BattleActData(who, arr, cmd, abilities,
                party ? BattleActData.ActType.Interrupt : BattleActData.ActType.Normal, tt,
                BattleActData.ArmType.Right, (BattleActData.ActAbilityType)0, 1, false);
            // "turn": not marked as a counter, so the target's counter conditions see it as a hit of a turn (a hit by
            // a counterattack matches none on the SNES: the AI host's CounterRules; BNW's Soul Train "if hit by Suplex")
            bool turn = a.Length > 4 && a[4] == "turn";
            act.isCounter = party && !turn;
            bm.BattleActExection.SetBattleActData(act);
            return $"queued: {Name(who)} command {command} ability {ab.Id} on {string.Join(", ", targets.Select(Name))}{(turn ? " (a turn's act)" : "")}";
        }
    }
}
