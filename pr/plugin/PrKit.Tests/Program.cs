using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using BepInEx.Configuration;
using HarmonyLib;
using PrKit;

// Tiny test runner (as Rules.Tests): each Test() prints PASS/FAIL; exit code = number of failures.
// Only the kit's parts that need no game run here: which PR a process name is, request files,
// feature switches and isolation. The rest is checked in game (kit.py run: [kit]/[check] lines).
static class Program
{
    static int failures, passes;

    static int Main()
    {
        Test("game from process name", GameNames);
        Test("request file parsing", Requests);
        Test("request file is taken once", RequestTakenOnce);
        Test("feature switches and isolation", FeatureSwitches);
        Test("snake_case table to master type name", Pascal);
        Test("SNES encounter rules: vanilla", EncountersVanilla);
        Test("SNES encounter rules: BNW's roll and tables", EncountersBnw);
        Console.WriteLine($"\n{passes} passed, {failures} failed");
        return failures;
    }

    static void Test(string name, Action body)
    {
        try { body(); passes++; Console.WriteLine($"PASS  {name}"); }
        catch (Exception e) { failures++; Console.WriteLine($"FAIL  {name}: {e.Message}"); }
    }

    static void Eq<T>(T want, T got, string what)
    {
        if (!EqualityComparer<T>.Default.Equals(want, got)) throw new Exception($"{what}: want {want}, got {got}");
    }

    static void GameNames()
    {
        Eq(PrGame.FF6, Game.FromProcessName("FINAL FANTASY VI"), "FF6");
        Eq(PrGame.FF5, Game.FromProcessName("FINAL FANTASY V.exe"), "FF5 with .exe");
        Eq(PrGame.FF4, Game.FromProcessName("final fantasy iv"), "lower case");
        Eq(PrGame.FF1, Game.FromProcessName("FINAL FANTASY"), "FF1 (no numeral)");
        Eq(PrGame.FF2, Game.FromProcessName("FINAL FANTASY II PR"), "folder name");
        Eq(PrGame.FF3, Game.FromProcessName(@"D:\Games\FINAL FANTASY III.exe"), "a path");
        Eq(PrGame.Unknown, Game.FromProcessName("FINAL FANTASY VII"), "not a PR");
        Eq(PrGame.Unknown, Game.FromProcessName(""), "empty");
        Eq(PrGame.Unknown, Game.FromProcessName(null), "null");
        Eq(1173810, Game.SteamAppId(PrGame.FF5), "FF5 app id");
        Eq("FINAL FANTASY VI", Game.Title(PrGame.FF6), "FF6 title");
    }

    static void Requests()
    {
        var d = RequestFile.Parse("harness=1\nport = 47900\r\n# a comment\nflags=-eer 2 4 -scan;preset=moogle cup\nverbose\nx=a=b\n=skipped\n");
        Eq("1", d["harness"], "harness");
        Eq(47900, RequestFile.Int(d, "port", 0), "port");
        Eq("-eer 2 4 -scan", d["flags"], "flags with spaces");
        Eq("moogle cup", d["preset"], "';' separates lines");
        Eq(true, RequestFile.Flag(d, "verbose"), "a bare word is a switch");
        Eq("a=b", d["x"], "value keeps its '='");
        Eq(false, d.ContainsKey(""), "no empty key");
        Eq(true, RequestFile.Flag(d, "HARNESS"), "keys ignore case");
        Eq(5, RequestFile.Int(d, "missing", 5), "fallback");
        Eq(false, RequestFile.Flag(null, "x"), "no request");
    }

    static void RequestTakenOnce()
    {
        var path = Path.Combine(Path.GetTempPath(), $"prkit_test_{Guid.NewGuid():N}.request");
        File.WriteAllText(path, "minutes=5\n");
        var first = RequestFile.Take(path);
        Eq("5", first?["minutes"], "first read");
        Eq(false, File.Exists(path), "deleted after reading");
        Eq(null, RequestFile.Take(path), "second read finds none");
    }

    class On : Feature { public bool Applied; public On() : base("Battle", "On", true, "on by default") { } public override void Apply(Harmony h) => Applied = true; }
    class Off : Feature { public bool Applied; public Off() : base("Battle", "Off", false, "off by default") { } public override void Apply(Harmony h) => Applied = true; }
    class Broken : Feature { public Broken() : base("Battle", "Broken", true, "throws") { } public override void Apply(Harmony h) => throw new InvalidOperationException("no such method"); }
    class Always : Feature
    {
        public bool Applied;
        public ConfigEntry<int> Extra;
        public override void Bind() => Extra = Setting("Extra", 7, "an extra setting");
        public override void Apply(Harmony h) => Applied = true;
    }

    static void FeatureSwitches()
    {
        var cfgPath = Path.Combine(Path.GetTempPath(), $"prkit_test_{Guid.NewGuid():N}.cfg");
        try
        {
            File.WriteAllText(cfgPath, "[Battle]\nOn = false\n");   // the player turned "On" off
            var host = new FeatureHost(new ConfigFile(cfgPath, true), null) { TestRuns = false };
            var on = host.Add(new On());
            var off = host.Add(new Off());
            var broken = host.Add(new Broken());
            var always = host.Add(new Always());
            host.ApplyAll();
            Eq(false, on.Enabled, "config turned On off");
            Eq(false, on.Applied, "a feature off isn't applied");
            Eq(false, off.Enabled, "default off");
            Eq(false, broken.Enabled, "a feature that throws is turned off");
            Eq(true, always.Enabled && always.Applied, "no switch: always on, applied after the broken one");
            Eq(7, always.Extra.Value, "its extra setting");
            Eq(always, host.Get<Always>(), "Get<T>");
            var text = File.ReadAllText(cfgPath);
            foreach (var key in new[] { "On = false", "Off = false", "Broken = true", "Extra = 7", "PerfLog = false" })
                if (!text.Contains(key)) throw new Exception($"config file lacks '{key}'");
        }
        finally { File.Delete(cfgPath); }
    }

    static void Pascal()
    {
        Eq("MonsterParty", LiveData.Pascal("monster_party"), "monster_party");
        Eq("Item", LiveData.Pascal("item"), "item");
        Eq("AbilityRandomGroup", LiveData.Pascal("ability_random_group"), "ability_random_group");
    }

    // PrKit/Ff6/SnesEncounterRules.cs: vanilla's numbers (WcTest's encounters check expects these means),
    // a step's danger, the relics
    static void EncountersVanilla()
    {
        var r = PrKit.Ff6.SnesEncounterRules.Vanilla;
        Eq(23.35, Math.Round(r.MeanSteps(0xC0), 2), "world normal");
        Eq(33.61, Math.Round(r.MeanSteps(0x60), 2), "world low");
        Eq(31.1, Math.Round(r.MeanSteps(0x70), 2), "other maps normal");
        Eq(13.86, Math.Round(r.MeanSteps(0x200), 2), "other maps very high");
        Eq(0x60, r.Rate(true, 0, true, false), "the Charm Bangle halves");
        Eq(0, r.Rate(false, 2, false, true), "the Moogle Charm stops");
        Eq(0, r.Rate(true, 3, false, false), "world code 3: none");
        Eq(0, r.Rate(false, PrKit.Ff6.SnesEncounterRules.NoBattles, false, false), "no battles");
        Eq(200, r.Roll(200), "the roll is the random byte");
        Eq(false, PrKit.Ff6.SnesEncounterRules.Advance(0xFE00, 0x200, 255, out int after), "roll 255 at $FF: never");
        Eq(0xFF00, after, "the danger stops at $FF00");
        Eq(true, PrKit.Ff6.SnesEncounterRules.Advance(0x100, 0x70, 0, out after), "roll 0 at $01");
        Eq(-2, r.WorldCode(1, 0, 0), "no tables: the mod's own RateCode");
    }

    // BNW's (its ROM, tools/port_encounter_rates.py): the roll 4 + random x 233 / 256, so no battle until
    // the danger's high byte passes 4; a zone byte's terrain groups; the data as bnw_data.json has it
    static void EncountersBnw()
    {
        var r = PrKit.Ff6.SnesEncounterRules.Parse(System.Text.Json.JsonDocument.Parse(
            "{\"name\":\"bnw\",\"roll\":{\"add\":4,\"range\":233},\"world_zones\":{\"1\":[" + string.Join(",", new int[64].Select((_, i) => i == 1 ? 0x23 : 0xFF)) + "]}," +
            "\"foot_group\":{\"1\":{\"4\":0,\"9\":1,\"15\":2}},\"set_codes\":{\"144\":-1,\"219\":2}}").RootElement);
        Eq("bnw", r.Name, "name");
        Eq(4, r.Roll(0), "the lowest roll");
        Eq(236, r.Roll(255), "the highest roll");
        Eq(0.0, r.BattleChance(0x4FF), "no battle at $04FF");
        Eq(true, r.BattleChance(0x500) > 0, "a chance at $0500");
        Eq(37.76, Math.Round(r.MeanSteps(0x70), 2), "other maps normal");
        Eq(26.97, Math.Round(r.MeanSteps(0xC0), 2), "world normal");
        Eq(0, r.WorldCode(1, 1, 4), "zone 1 ($23) grass: normal");
        Eq(2, r.WorldCode(1, 1, 9), "zone 1 forest: high");
        Eq(0, r.WorldCode(1, 1, 15), "zone 1 desert: normal");
        Eq(3, r.WorldCode(1, 0, 4), "zone 0 ($FF): none");
        Eq(0, r.WorldCode(1, 1, 99), "an unknown ground: group 0");
        Eq(-1, r.MapCode(144), "set 144: no battles");
        Eq(2, r.MapCode(219), "set 219: high");
        Eq(0, r.MapCode(5), "a set not listed: normal");
        Eq(0x180, r.Rate(true, r.WorldCode(1, 1, 9), false, false), "the rate");
    }
}
