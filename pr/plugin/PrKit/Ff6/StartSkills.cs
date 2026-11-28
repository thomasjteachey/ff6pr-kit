using System;
using System.Collections.Generic;
using System.Linq;
using Last.Data.User;
using Last.Management;

namespace PrKit.Ff6
{
    // FF6's technique sets (SwdTech, Blitz, Lore, Dance, Rage) known from the start or learned on the party's behalf.
    // In the SNES they are the party's: whoever holds the command uses the party's set. In the PR they are each
    // character's own abilities, learned to a skill level (100 = known). A mod that gives skills outside the game's own
    // learning (a randomizer's start skills, rages won while nobody holds Rage) teaches them to the command's holders:
    // Teach(command, abilities). Abilities for a command nobody holds yet wait in a queue (this session only) until
    // TeachPending() finds a holder (call it on joins / the field's sync). Opt-in: nothing runs unless a mod calls it.
    // Generalized from Worlds Collide's WcRages/WcSkills (2026-11-20, the kit lead's OK; WC moves onto it later).
    public static class StartSkills
    {
        // the PR's command ids
        public const int Bushido = 12, Blitz = 15, Lore = 17, Dance = 22, Rage = 23;

        // (command, first ability, last ability): the PR's abilities of each set (Rage: 799 + PR monster id)
        public static readonly (int Command, int First, int Last)[] Sets =
        {
            (Bushido, 124, 131), (Blitz, 132, 139), (Lore, 140, 163), (Dance, 164, 171), (Rage, 800, 1054),
        };

        public static string Tag = "[kit]";
        public static Action<string, Exception> Warn = Hooks.WarnOnce;   // a mod's own warning (WC: WcRunner.WarnOnce)
        public static string Last = "";
        static readonly Dictionary<int, HashSet<int>> pending = new Dictionary<int, HashSet<int>>();

        // the playable characters (status 1 Terra .. 14 Umaro) the player owns
        public static IEnumerable<OwnedCharacterData> Owned()
        {
            var list = UserDataManager.Instance()?.OwnedCharacterList;
            if (list == null) yield break;
            foreach (var c in list)
                if (c != null && c.characterStatusId >= 1 && c.characterStatusId <= 14) yield return c;
        }

        public static bool Has(OwnedCharacterData c, int command)
        {
            var list = c?.CommandList;
            if (list == null) return false;
            foreach (var x in list) if (x != null && x.Id == command) return true;
            return false;
        }

        // the owned characters who hold a command
        public static List<OwnedCharacterData> Holders(int command) => Owned().Where(c => Has(c, command)).ToList();

        // A character's abilities are held twice: OwnedAbilityList, and AbilityDictionary (Command -> its abilities),
        // which a save's load fills (the save keeps both). The Abilities menu shows an ability known in EITHER copy; the
        // two can hold different OwnedAbility objects for one ability, and OwnedCharacterClient.AddAbility adds a new
        // one to the list only. So a skill level written to the list alone (an un-learn, or a teach of a list entry at
        // 0) leaves the menu's copy as it was (BNW's Gau on the Deck, 2026-11-27). Everything below reads and writes
        // both: Knows = known in every copy, Shown = in any (what the menu shows), Teach / Forget set both, and Teach
        // puts the list's object in the dictionary's group for its set when the dictionary lacks it.

        // a character's ability entries: the list's (list), the dictionary's (menu)
        public static IEnumerable<OwnedAbility> Entries(OwnedCharacterData c, bool list = true, bool menu = true)
        {
            if (list && c?.OwnedAbilityList != null)
                foreach (var a in c.OwnedAbilityList) if (a?.Ability != null) yield return a;
            if (menu && c?.AbilityDictionary != null)
                foreach (var group in c.AbilityDictionary.Values)
                    if (group != null) foreach (var a in group) if (a?.Ability != null) yield return a;
        }

        // one ability's entries, both copies
        public static List<OwnedAbility> Entries(OwnedCharacterData c, int ability) =>
            Entries(c).Where(a => a.Ability.Id == ability).ToList();

        // known = learned to 100 in every copy that has it (the PR gives Gau an entry for every rage, the unknown ones at
        // 0). A copy at less is what Teach repairs, so `!Knows(c, id) && Teach(c, id)` mends a half-known ability.
        public static bool Knows(OwnedCharacterData c, int ability)
        {
            bool any = false;
            foreach (var a in Entries(c, ability))
            {
                if (a.SkillLevel < 100) return false;
                any = true;
            }
            return any;
        }

        // known to 100 in either copy: what the Abilities menu shows (an un-learn's test, a count of what the player has)
        public static bool Shown(OwnedCharacterData c, int ability) => Entries(c, ability).Any(a => a.SkillLevel >= 100);

        // the highest skill level in either copy (a spell partly learned from an esper: 1-99); 0 when it has none
        public static int Level(OwnedCharacterData c, int ability)
        {
            int level = 0;
            foreach (var a in Entries(c, ability)) level = Math.Max(level, a.SkillLevel);
            return level;
        }

        // the abilities in [first, last] shown known (either copy), sorted
        public static List<int> Known(OwnedCharacterData c, int first, int last)
        {
            var known = new SortedSet<int>();
            foreach (var a in Entries(c))
                if (a.Ability.Id >= first && a.Ability.Id <= last && a.SkillLevel >= 100) known.Add(a.Ability.Id);
            return known.ToList();
        }

        // one character learns one ability to 100 in both copies (a list entry added if it has none, and put in the
        // dictionary's group for its set when the dictionary has none)
        public static bool Teach(OwnedCharacterData c, int ability)
        {
            if (c == null) return false;
            OwnedAbility owned = Entries(c, true, false).LastOrDefault(a => a.Ability.Id == ability);
            if (owned == null)
            {
                var added = new OwnedCharacterClient().AddAbility(c.Id, ability);
                owned = Entries(c, true, false).LastOrDefault(a => a.Ability.Id == ability) ?? added;
            }
            if (owned == null) return false;
            owned.SkillLevel = 100;
            foreach (var a in Entries(c, ability)) if (a.SkillLevel < 100) a.SkillLevel = 100;
            AddToMenu(c, owned);
            return true;
        }

        // Teach for a count of new skills: true only if the player didn't see it known before (a half-known one is
        // mended, not counted)
        public static bool TeachNew(OwnedCharacterData c, int ability)
        {
            bool shown = Shown(c, ability);
            if (!Knows(c, ability)) Teach(c, ability);
            return !shown && Shown(c, ability);
        }

        // one character un-learns one ability: skill level 0 in both copies. True if any copy had some.
        public static bool Forget(OwnedCharacterData c, int ability)
        {
            bool had = false;
            foreach (var a in Entries(c, ability))
                if (a.SkillLevel > 0) { a.SkillLevel = 0; had = true; }
            return had;
        }

        // every ability `which` picks that the character has any skill level in (either copy) is un-learned; returns
        // them, sorted
        public static List<int> Forget(OwnedCharacterData c, Func<int, bool> which)
        {
            var ids = new SortedSet<int>();
            foreach (var a in Entries(c)) if (a.SkillLevel > 0 && which(a.Ability.Id)) ids.Add(a.Ability.Id);
            foreach (var id in ids) Forget(c, id);
            return ids.ToList();
        }

        // abilities whose dictionary group can be told by its neighbours: the sets, spells, Magitek
        static (int First, int Last, int Command) Family(int ability)
        {
            foreach (var (command, first, last) in Sets)
                if (ability >= first && ability <= last) return (first, last, command);
            if (SnesNaturalMagic.IsSpell(ability)) return (SnesNaturalMagic.First, SnesNaturalMagic.Last, -1);
            if (ability >= 218 && ability <= 225) return (218, 225, -1);   // Magitek
            return (0, -1, -1);
        }

        // the list's object into the dictionary when no group there has the ability: every group keyed by the set's
        // command or holding another ability of its family (a character with no such group, or no dictionary yet: a
        // join in this session, is left alone; the game builds it from the list)
        static void AddToMenu(OwnedCharacterData c, OwnedAbility owned)
        {
            var dict = c?.AbilityDictionary;
            int id = owned.Ability.Id;
            if (dict == null || Entries(c, false, true).Any(a => a.Ability.Id == id)) return;
            var (first, last, command) = Family(id);
            if (last < first) return;
            foreach (var kv in dict)
            {
                var group = kv.Value;
                if (group == null) continue;
                bool mine = command >= 0 && kv.Key != null && kv.Key.Id == command;
                if (!mine)
                    foreach (var a in group)
                        if (a?.Ability != null && a.Ability.Id >= first && a.Ability.Id <= last) { mine = true; break; }
                if (mine) group.Add(owned);
            }
        }

        // every holder of `command` learns `abilities` (those not known yet); with no holder they wait (TeachPending)
        // unless queue is false (a seed's start skills, read again on every call: a queue would outlive a seed switch).
        // Returns how many were taught.
        public static int Teach(int command, IEnumerable<int> abilities, bool queue = true)
        {
            var ids = abilities.Distinct().ToList();
            var holders = Holders(command);
            if (holders.Count == 0)
            {
                if (!queue) return 0;
                if (!pending.TryGetValue(command, out var wait)) pending[command] = wait = new HashSet<int>();
                foreach (var id in ids) wait.Add(id);
                return 0;
            }
            int n = 0;
            foreach (var c in holders)
                foreach (var id in ids)
                    if (!Knows(c, id) && Teach(c, id)) n++;
            if (n > 0) Note($"command {command}: {n} taught to {string.Join(",", holders.Select(h => h.characterStatusId))}");
            return n;
        }

        // the queued abilities to the commands' holders, once someone holds them
        public static int TeachPending()
        {
            int n = 0;
            foreach (var command in pending.Keys.ToList())
            {
                if (Holders(command).Count == 0) continue;
                var ids = pending[command].ToList();
                n += Teach(command, ids);
                pending.Remove(command);          // only once taught (a throw keeps them queued)
            }
            return n;
        }

        public static int Pending(int command) => pending.TryGetValue(command, out var s) ? s.Count : 0;

        // the queued abilities of a command, taken out of the queue (a mod that keeps them its own way: BC teaches them
        // to an owned character, so the save keeps them and Sync shares them with a later holder)
        public static List<int> TakePending(int command)
        {
            if (!pending.TryGetValue(command, out var s)) return new List<int>();
            pending.Remove(command);
            return s.ToList();
        }

        // The SNES's party-wide sets: every holder of a set's command knows what any owned character knows of that set
        // (taught to 100). For a mod that moves commands (WC, BC's `o`): call it on joins and every few seconds in the
        // field. Returns what was taught ("" when nothing). From Worlds Collide's WcSkills.Sync (2026-11-21).
        public static string LastSync = "";

        public static string Sync() => Sync(null);

        // only these commands' sets (null: every set)
        public static string Sync(ICollection<int> commands)
        {
            var report = new List<string>();
            try
            {
                var owned = Owned().ToList();
                foreach (var (command, first, last) in Sets)
                {
                    if (commands != null && !commands.Contains(command)) continue;
                    var holders = owned.Where(c => Has(c, command)).ToList();
                    if (holders.Count == 0) continue;
                    var known = new HashSet<int>();
                    foreach (var c in owned) known.UnionWith(Known(c, first, last));   // shown in either copy
                    int taught = 0;
                    foreach (var h in holders)
                        foreach (var id in known)
                            if (!Knows(h, id) && Teach(h, id)) taught++;
                    if (taught > 0) report.Add($"command {command}: {taught} taught to {string.Join(",", holders.Select(h => h.characterStatusId))}");
                }
            }
            catch (Exception e) { Warn("skills-sync", e); }
            if (report.Count == 0) return "";
            LastSync = string.Join("; ", report);
            Kit.Info($"{Tag} skills shared: {LastSync}");
            return LastSync;
        }

        // Harness `skillcopies` (a mod registers it: RegisterHarness). For a loaded save (savesandbox=, where a save's
        // load has built the menu's dictionary): per owned character, a known ability is forgotten (0 in every copy,
        // not shown) and taught back (100 in every copy), and an unknown ability taken out of the menu's copy is taught (back
        // in the menu's group: AddToMenu) and forgotten again. Test runs never save.
        public static void RegisterHarness() => Harness.Register("skillcopies", a => CopiesCheck(),
            "skillcopies: StartSkills' Forget / Teach on both copies of each owned character's abilities (list + the menu's dictionary)");

        static string CopiesCheck()
        {
            var lines = new List<string>();
            bool ok = true;
            void Check(bool pass, string line) { ok &= pass; lines.Add((pass ? "ok: " : "FAILED: ") + line); }
            string Levels(OwnedCharacterData c, int id) =>
                $"list [{string.Join(" ", Entries(c, true, false).Where(x => x.Ability.Id == id).Select(x => x.SkillLevel))}] " +
                $"menu [{string.Join(" ", Entries(c, false, true).Where(x => x.Ability.Id == id).Select(x => x.SkillLevel))}]";
            int withMenu = 0;
            try
            {
                foreach (var c in Owned().ToList())
                {
                    var menu = Entries(c, false, true).ToList();
                    if (menu.Count == 0) continue;
                    withMenu++;
                    string who = $"character {c.characterStatusId}";
                    // a known ability in both copies (a rage first: Gau's Deck bug)
                    int known = menu.Where(a => a.SkillLevel >= 100).Select(a => a.Ability.Id)
                        .Where(id => Entries(c, true, false).Any(x => x.Ability.Id == id))
                        .OrderByDescending(id => id >= 800).FirstOrDefault();
                    if (known != 0)
                    {
                        bool apart = Entries(c, true, false).Where(x => x.Ability.Id == known)
                            .All(x => !menu.Any(y => y.Ability.Id == known && y.Pointer == x.Pointer));
                        string before = Levels(c, known);
                        bool had = Forget(c, known);
                        Check(had && Level(c, known) == 0 && !Shown(c, known),
                            $"{who} forgot {known} (copies {(apart ? "separate objects" : "one object")}): {before} -> {Levels(c, known)}");
                        Teach(c, known);
                        Check(Knows(c, known) && Entries(c, false, true).Any(x => x.Ability.Id == known),
                            $"{who} taught {known} back: {Levels(c, known)}");
                    }
                    else lines.Add($"skipped: {who} knows nothing in both copies");
                    // AddToMenu: an unknown ability (0 in both copies) whose menu group holds another of its family is
                    // taken out of the menu; Teach puts the list's object back in that group
                    int probe = 0;
                    foreach (var kv in c.AbilityDictionary)
                    {
                        var g = kv.Value;
                        if (g == null) continue;
                        foreach (var x in g)
                        {
                            if (x?.Ability == null || x.SkillLevel != 0 || Level(c, x.Ability.Id) != 0) continue;
                            var (first, last, _) = Family(x.Ability.Id);
                            if (last < first || !Entries(c, true, false).Any(y => y.Ability.Id == x.Ability.Id)) continue;
                            int same = 0;
                            foreach (var y in g) if (y?.Ability != null && y.Ability.Id >= first && y.Ability.Id <= last) same++;
                            if (same >= 2) { probe = x.Ability.Id; break; }
                        }
                        if (probe != 0) break;
                    }
                    if (probe != 0)
                    {
                        foreach (var kv in c.AbilityDictionary)
                        {
                            var g = kv.Value;
                            if (g == null) continue;
                            for (int i = g.Count - 1; i >= 0; i--)
                                if (g[i]?.Ability != null && g[i].Ability.Id == probe) g.RemoveAt(i);
                        }
                        bool gone = !Entries(c, false, true).Any(x => x.Ability.Id == probe);
                        Teach(c, probe);
                        bool back = Entries(c, false, true).Any(x => x.Ability.Id == probe);
                        Check(gone && back && Knows(c, probe), $"{who}: {probe} taken out of the menu's copy, taught: {Levels(c, probe)}");
                        Forget(c, probe);
                        Check(!Shown(c, probe), $"{who} forgot {probe} again: {Levels(c, probe)}");
                    }
                    else lines.Add($"skipped: {who} has no unknown ability to take out of the menu");
                }
            }
            catch (Exception e) { return $"skillcopies: FAILED: {e.GetType().Name}: {e.Message}"; }
            Check(withMenu > 0, $"{withMenu} owned characters have the menu's dictionary (a loaded save)");
            return $"skillcopies: {(ok ? "ok" : "FAILED")}\n" + string.Join("\n", lines);
        }

        static void Note(string what)
        {
            Last = what;
            Kit.Info($"{Tag} skills: {what}");
        }
    }
}
