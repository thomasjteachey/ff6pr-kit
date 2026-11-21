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
        Test("art new groups: art.json parsing, keys and the atlas address", ArtNewGroupsPlan);
        Test("SNES encounter rules: vanilla", EncountersVanilla);
        Test("SNES encounter rules: BNW's roll and tables", EncountersBnw);
        Test("monster images: recipe, pixels, thumbnail", MonsterImagesRecipe);
        Test("monster images: files, keys, marker", MonsterImagesWrite);
        Test("monster images: slot-form color tables", MonsterImagesSlots);
        Test("SNES Suplex: the monsters it misses", SuplexRules);
        Test("SNES ATB: fill rates, waits, Jump's air time", AtbRules);
        Test("SNES ATB: which acts wait", AtbChants);
        Test("SNES ATB: BNW's Speed Balance, Quickfill, time held for actions", AtbBnw);
        Test("SNES status clock on a fake clock: steps, Regen, Poison, Haste", StatusClockTimes);
        Test("SNES status clock: a mod's add filter and step kind (BC's junctions)", StatusClockHooks);
        Test("self-tests: found by name, selected", SelfTestsChecks.Discovery);
        Test("self-tests: run on a fake clock (waits, timeouts, errors, fixtures)", SelfTestsChecks.Running);
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

    // PrKit/Ff6/SnesSuplexRules.cs (tests/test_snes_rules.py checks the list against the US ROM)
    static void SuplexRules()
    {
        var v = PrKit.Ff6.SnesSuplexRules.VanillaNoSuplex;
        Eq(159, v.Length, "vanilla's can't-suplex monsters (146 named + 13 unnamed slots)");
        Eq(v.Length, v.Distinct().Count(), "no id twice");
        if (v.Any(id => id < 1 || id > 384)) throw new Exception("an id outside the PR's 1-384 SNES rows");
        var set = new HashSet<int>(v);
        const int suplex = PrKit.Ff6.SnesSuplexRules.SuplexAbility, whisper = 15, ghostTrain = 263, vargas = 260;
        Eq(true, PrKit.Ff6.SnesSuplexRules.Misses(suplex, whisper, set), "Whisper can't be suplexed");
        Eq(true, PrKit.Ff6.SnesSuplexRules.Misses(suplex, vargas, set), "Vargas can't be suplexed");
        Eq(false, PrKit.Ff6.SnesSuplexRules.Misses(suplex, ghostTrain, set), "the Phantom Train can be");
        Eq(false, PrKit.Ff6.SnesSuplexRules.Misses(1, whisper, set), "only Suplex misses (Attack doesn't)");
        Eq(false, PrKit.Ff6.SnesSuplexRules.Misses(suplex, 0, set), "not a monster (a character)");
        Eq(false, PrKit.Ff6.SnesSuplexRules.Misses(suplex, whisper, new HashSet<int>()), "a mod with an empty list");
        Eq(true, PrKit.Ff6.SnesSuplexRules.Misses(200, whisper, set, 200), "a mod's own Suplex ability id");
        var copies = PrKit.Ff6.SnesSuplexRules.VanillaNoSuplexCopies;
        Eq(18, copies.Length, "Coliseum copies of can't-suplex monsters");
        if (copies.Any(id => id < 500 || set.Contains(id))) throw new Exception("a copy below 500 or already a regular");
        Eq(177, PrKit.Ff6.SnesSuplexRules.VanillaWithCopies.Length, "regulars + copies");
        Eq(true, PrKit.Ff6.SnesSuplexRules.Misses(suplex, 500, new HashSet<int>(PrKit.Ff6.SnesSuplexRules.VanillaWithCopies)),
           "Suplex misses a flagged monster's Coliseum copy");
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

    // PrKit/ArtNewGroups.cs: a field NPC group the game never shipped, made from one it has (ArtSwap's game side)
    static void ArtNewGroupsPlan()
    {
        using var doc = System.Text.Json.JsonDocument.Parse(
            "{\"new_groups\": {\"mo_ted_s183\": {\"like\": \"mo_ff6_n001_c00\"}, \"mo_x\": {\"like\": \"mo_ff6_n004_c00\", \"atlas\": \"MO_X_ATLAS\"}, " +
            "\"bad\": {}}, \"atlases\": {}}");
        var gs = ArtNewGroups.Parse(doc.RootElement);
        Eq(2, gs.Count, "groups (one without like skipped)");
        Eq("MO_TED_S183", gs[0].Atlas, "default atlas name: the group in capitals");
        Eq("MO_X_ATLAS", gs[1].Atlas, "an atlas name given");
        using var none = System.Text.Json.JsonDocument.Parse("{\"sprites\": {}}");
        Eq(0, ArtNewGroups.Parse(none.RootElement).Count, "no new_groups: nothing (WC, BNW, BC)");
        const string dir = "Assets/GameAssets/Serial/Res/Chara/Map/MO_FF6_N001_C00/";
        var like = new Dictionary<string, string>
        {
            ["anim_info"] = dir + "anim_info", ["Default_00"] = dir + "Default_00",
            ["MO_FF6_N001_C00"] = dir + "MO_FF6_N001_C00",
        };
        var plan = ArtNewGroups.Keys(gs[0], like);
        Eq("Assets/GameAssets/Serial/Res/Chara/Map/MO_TED_S183/MO_TED_S183", plan.NewAtlasAddress, "the new atlas address");
        Eq(dir + "MO_FF6_N001_C00", plan.LikeAtlasAddress, "like's atlas");
        Eq(dir + "anim_info", plan.Keys["anim_info"], "anim_info: like's (same frame names)");
        Eq(dir + "Default_00", plan.Keys["Default_00"], "a frame: like's address");
        Eq(plan.NewAtlasAddress, plan.Keys["MO_TED_S183"], "the group's atlas key: the new address");
        Eq(dir + "MO_FF6_N001_C00", plan.Keys["MO_FF6_N001_C00"], "like's atlas key kept: loading the group loads it");
        Eq(null, ArtNewGroups.Keys(gs[0], new Dictionary<string, string> { ["anim_info"] = "x" }), "no atlas key in like: none");
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

    // MonsterImages (game-free): a synthetic recipe with one new-art image (palette + pixels, a
    // thumbnail at 3x) built into a scratch Magicite folder: pixels, PNG, sprite data, keys, marker.
    static string MonsterRecipeJson()
    {
        // 3x2 sprite: slots 0 (clear), 1 (red), 2 (blue)
        var idx = new byte[] { 0, 1, 2, 1, 1, 0 };
        string b64;
        using (var ms = new MemoryStream())
        {
            using (var z = new System.IO.Compression.ZLibStream(ms, System.IO.Compression.CompressionLevel.Optimal, true)) z.Write(idx, 0, idx.Length);
            b64 = Convert.ToBase64String(ms.ToArray());
        }
        return "{\"imgs\": {\"id\": \"test1\", \"version\": 1, \"images\": [{\"monster\": 7, \"name\": \"Test\", \"key\": \"MN_FF6_001_B007\", " +
               "\"group\": \"mn_ff6_001\", \"w\": 3, \"h\": 2, \"palette\": [\"000000\", \"ff0000\", \"0000ff\"], \"pixels\": \"" + b64 + "\", " +
               "\"thumb\": {\"group\": \"mt_ff6_001_b007\", \"x\": 100, \"y\": 110, \"scale\": 3}}]}}";
    }

    static void MonsterImagesRecipe()
    {
        Eq(null, MonsterImageRecipe.FromJson("{\"x\": 1}", "imgs"), "no recipe");
        var r = MonsterImageRecipe.FromJson(MonsterRecipeJson(), "imgs");
        Eq("test1", r.Id, "id");
        var img = r.Images.Single();
        Eq(7, img.Monster, "monster");
        Eq("mt_ff6_001_b007", img.Thumb.Group, "thumb group");
        Eq(3, img.Thumb.Scale, "thumb scale");
        var px = MonsterImages.Build(".", img, new Dictionary<string, Dictionary<string, BundleTexture>>(), _ => { });
        Eq(3 * 2 * 4, px.Length, "rgba size");
        Eq(0, (int)px[3], "slot 0 is clear");
        Eq("255,0,0,255", $"{px[4]},{px[5]},{px[6]},{px[7]}", "slot 1 red");
        Eq("0,0,255,255", $"{px[8]},{px[9]},{px[10]},{px[11]}", "slot 2 blue");
        var th = MonsterImages.BuildThumb(".", img, px, null, _ => { });
        Eq(MonsterThumb.Size * MonsterThumb.Size * 4, th.Length, "thumb size");
        int at(int x, int y) => 4 * (y * MonsterThumb.Size + x);
        Eq(255, (int)th[at(103, 110) + 0], "thumb: art (1,0) at 3x is red");
        Eq(255, (int)th[at(108, 112) + 2], "thumb: art (2,0) at 3x is blue");
        Eq(0, (int)th[at(100, 110) + 3], "thumb: art (0,0) clear");
        Eq(0, (int)th[at(99, 110) + 3], "thumb: outside the art clear");
    }

    // A recolor's table as slots (the k-th distinct opaque color of the player's source image, sorted) resolved
    // against that image; refused when the image isn't the one the table was made on (sha1, color count).
    static void MonsterImagesSlots()
    {
        var json = "{\"imgs\": {\"id\": \"s\", \"images\": [{\"monster\": 7, \"key\": \"K\", \"group\": \"g\", \"w\": 2, \"h\": 2, " +
                   "\"from\": \"F\", \"colors\": 3, \"map_slots\": [\"0:111111\", \"2:333333\"]}]}}";
        var img = MonsterImageRecipe.FromJson(json, "imgs").Images.Single();
        Eq(2, img.SlotMap.Count, "slots read");
        // the source: 0x0000ff, 0xff0000, a clear pixel, 0x00ff00 -> sorted 0000ff (0), 00ff00 (1), ff0000 (2)
        var src = new byte[] { 0, 0, 255, 255, 255, 0, 0, 255, 9, 9, 9, 0, 0, 255, 0, 255 };
        var warnings = new List<string>();
        Eq(true, MonsterImages.ResolveSlots(img, src, warnings.Add), "resolved");
        Eq(0x111111, img.Map[0x0000ff], "slot 0 = the lowest color");
        Eq(0x333333, img.Map[0xff0000], "slot 2 = the highest");
        Eq(false, img.Map.ContainsKey(0x00ff00), "slot 1 unchanged");
        var other = MonsterImageRecipe.FromJson(json, "imgs").Images.Single();
        Eq(false, MonsterImages.ResolveSlots(other, new byte[] { 1, 1, 1, 255 }, warnings.Add), "another image: refused");
        var sha = MonsterImageRecipe.FromJson(json.Replace("\"colors\"", "\"from_sha1\": \"00\", \"colors\""), "imgs").Images.Single();
        Eq(false, MonsterImages.ResolveSlots(sha, src, warnings.Add), "another sha1: refused");
        Eq(2, warnings.Count, "two warnings");
        // both forms in one recipe: the slots still resolve (on top of the map), once
        var both = MonsterImageRecipe.FromJson(json.Replace("\"colors\"", "\"map\": [\"0000ff:444444\", \"00ff00:555555\", \"ff0000:666666\"], \"colors\""), "imgs").Images.Single();
        Eq(true, MonsterImages.ResolveSlots(both, src, warnings.Add), "both forms: resolved");
        Eq(0x111111, both.Map[0x0000ff], "both forms: slot 0 over the map");
        Eq(0x555555, both.Map[0x00ff00], "both forms: the map's own entry kept");
        Eq(true, both.SlotsResolved, "marked resolved");
    }

    static void MonsterImagesWrite()
    {
        var r = MonsterImageRecipe.FromJson(MonsterRecipeJson(), "imgs");
        var dir = Path.Combine(Path.GetTempPath(), $"prkit_monster_images_test_{Guid.NewGuid():N}");   // its own: two runs at once
        if (Directory.Exists(dir)) Directory.Delete(dir, true);
        var warn = new List<string>();
        var line = MonsterImages.Ensure(dir, dir, r, warn.Add);
        Eq(0, warn.Count, "warnings: " + string.Join("; ", warn));
        var img = r.Images[0];
        var png = File.ReadAllBytes(MonsterImages.PngPath(dir, img));
        Eq("89-50-4E-47-0D-0A-1A-0A", BitConverter.ToString(png, 0, 8), "PNG signature");
        Eq(3, png[16] << 24 | png[17] << 16 | png[18] << 8 | png[19], "PNG width");
        Eq(2, png[20] << 24 | png[21] << 16 | png[22] << 8 | png[23], "PNG height");
        var sd = File.ReadAllText(Path.ChangeExtension(MonsterImages.PngPath(dir, img), ".spriteData"));
        if (!sd.Contains("Rect = [0,0,3,2]") || !sd.Contains("Pivot = [0.5,0]")) throw new Exception("sprite data: " + sd);
        var keys = File.ReadAllText(Path.Combine(dir, "mn_ff6_001", "keys", "Export.json"));
        if (!keys.Contains("\"MN_FF6_001_B007\"") || !keys.Contains("Assets/GameAssets/Serial/Res/Battle/Monster/MN_FF6_001/MN_FF6_001_B007"))
            throw new Exception("keys: " + keys);
        if (!File.Exists(MonsterImages.ThumbPngPath(dir, img.Thumb))) throw new Exception("no thumbnail");
        var tkeys = File.ReadAllText(Path.Combine(dir, "mt_ff6_001_b007", "keys", "Export.json"));
        if (!tkeys.Contains("Res/UI/Common/Library/Thumbnail/MT_FF6_001_B007/Thumbnail")) throw new Exception("thumb keys: " + tkeys);
        if (!line.StartsWith("monster images: made 1 of 1 (+1")) throw new Exception(line);
        if (!MonsterImages.Ensure(dir, dir, r, warn.Add).EndsWith("up to date")) throw new Exception("second run should skip");
        // a new recipe id: the old groups go, the new ones are made
        var r2 = MonsterImageRecipe.FromJson(MonsterRecipeJson().Replace("\"test1\"", "\"test2\""), "imgs");
        if (MonsterImages.UpToDate(dir, r2)) throw new Exception("a new id isn't up to date");
        MonsterImages.Ensure(dir, dir, r2, warn.Add);
        Eq("test2", File.ReadAllLines(Path.Combine(dir, MonsterImages.Marker))[0], "marker id");
        Directory.Delete(dir, true);
    }

    // ---- the SNES's battle timing, game-free (architecture roadmap item 3): PrKit/Ff6/SnesAtbRules.cs and
    // SnesStatusClock.cs on a fake clock. The reference numbers are the BC lead's and WC's (Wc.Tests'
    // status-clock line, WcTest atb measured against the SNES).

    static void Near(double want, double got, double tol, string what)
    {
        if (double.IsNaN(got) || Math.Abs(want - got) > tol) throw new Exception($"{what}: want {want} (+-{tol}), got {got:0.0000}");
    }

    static void AtbRules()
    {
        Eq(96, PrKit.Ff6.SnesAtbRules.NormalK, "vanilla's normal multiplier");
        Eq(126, PrKit.Ff6.SnesAtbRules.HasteK, "vanilla's Haste multiplier");
        Eq(48, PrKit.Ff6.SnesAtbRules.SlowK, "vanilla's Slow multiplier");
        Eq(24, PrKit.Ff6.SnesAtbRules.MonsterSpeedTerm, "vanilla's monster battle-speed term");
        Near(19.2577, PrKit.Ff6.SnesAtbRules.Rate(50, false, 2, false, false), 0.00005, "Speed 50's fill per second (WcTest atb)");
        Near(25.2643, PrKit.Ff6.SnesAtbRules.Rate(50, false, 2, true, false), 0.00005, "Speed 50 with Haste");
        Near(9.6289, PrKit.Ff6.SnesAtbRules.Rate(50, false, 2, false, true), 0.00005, "Speed 50 with Slow");
        Near(9.6289, PrKit.Ff6.SnesAtbRules.Rate(50, false, 2, true, true), 0.00005, "Slow wins over Haste (C2/09D2)");
        Eq(PrKit.Ff6.SnesAtbRules.Rate(50, false, 0, false, false), PrKit.Ff6.SnesAtbRules.Rate(50, false, 5, false, false),
           "a character's fill ignores the battle speed");
        Eq(336, PrKit.Ff6.SnesAtbRules.AtbAdd(50, true, 2, false, false), "a Speed 50 monster at the default battle speed: 70 x 207 / 256 = 56, x 96 / 16");
        Eq(420, PrKit.Ff6.SnesAtbRules.AtbAdd(50, false, 2, false, false), "a character's add at Speed 50: 70 x 96 / 16");
        // Jump's air time: 224 x 256 at half the ATB's add a move: Speed 43 = 189 a move, 304 moves
        Near(304 / PrKit.Ff6.SnesAtbRules.TicksPerSecond, PrKit.Ff6.SnesAtbRules.JumpSeconds(43, false, 2, false, false), 1e-9, "Jump at Speed 43: 304 moves");
        Near(10.10, PrKit.Ff6.SnesAtbRules.JumpSeconds(43, false, 2, false, false), 0.02, "Jump at Speed 43 (WcTest: 10.10 s)");
        Near(52 / 60.0988, PrKit.Ff6.SnesAtbRules.WaitSeconds(16, 33, false, 0, false, false), 2 / 60.0988, "Fight's wait at Speed 33 (harness: 51-57 frames, 52 by the rule)");
        Near(104 / 60.0988, PrKit.Ff6.SnesAtbRules.WaitSeconds(32, 33, false, 0, false, false), 1e-9, "Magic's wait at Speed 33: 52 moves (1.73 s; the harness saw the act at 136 frames)");
        Eq(0.0, PrKit.Ff6.SnesAtbRules.WaitSeconds(0, 33, false, 0, false, false), "no wait");
        Eq(2, PrKit.Ff6.SnesAtbRules.BattleSpeedOf(2), "the PR's middle battle speed is the SNES's default");
        Eq(5, PrKit.Ff6.SnesAtbRules.BattleSpeedOf(0), "the PR's slowest is Bat.Speed 6");
        Eq(2, PrKit.Ff6.SnesAtbRules.BattleSpeedOf(9), "an unknown setting: the default");
        // a mod's own values (T-Edition: HasteK 144) take, and go back
        int was = PrKit.Ff6.SnesAtbRules.HasteK;
        try
        {
            PrKit.Ff6.SnesAtbRules.HasteK = 144;
            Eq(70 * 144 >> 4, PrKit.Ff6.SnesAtbRules.AtbAdd(50, false, 2, true, false), "T-Edition's Haste multiplier");
        }
        finally { PrKit.Ff6.SnesAtbRules.HasteK = was; }
    }

    // Brave New World's ATB (its c2.asm C2/09D2 ATBMultipliers, ef.asm EF/FBC8 Quickfill, C2/1124 nATB): the kit's
    // settings for it give BNW's numbers, and the vanilla defaults (WC, BC, T-Edition) are untouched once put back.
    static void AtbBnw()
    {
        var R = typeof(PrKit.Ff6.SnesAtbRules);
        int nk = PrKit.Ff6.SnesAtbRules.NormalK, hk = PrKit.Ff6.SnesAtbRules.HasteK, sk = PrKit.Ff6.SnesAtbRules.SlowK;
        int cb = PrKit.Ff6.SnesAtbRules.CharBias, mb = PrKit.Ff6.SnesAtbRules.MonsterBias;
        bool mbs = PrKit.Ff6.SnesAtbRules.MonsterBattleSpeed, mhm = PrKit.Ff6.SnesAtbRules.MonsterHalfMore;
        Eq(20, cb, "vanilla's character bias");
        Eq(20, mb, "vanilla's monster bias");
        Eq(true, mbs, "vanilla's monsters go through the battle-speed term");
        Eq(false, mhm, "vanilla's monster multiplier is k");
        try
        {
            PrKit.Ff6.SnesAtbRules.NormalK = 75; PrKit.Ff6.SnesAtbRules.HasteK = 90; PrKit.Ff6.SnesAtbRules.SlowK = 60;
            PrKit.Ff6.SnesAtbRules.CharBias = 51; PrKit.Ff6.SnesAtbRules.MonsterBattleSpeed = false;
            PrKit.Ff6.SnesAtbRules.MonsterHalfMore = true;
            Eq(75 * 81 >> 4, PrKit.Ff6.SnesAtbRules.AtbAdd(30, false, 2, false, false), "a Speed 30 character: 75 x (30 + 51) / 16 = 379");
            Near(17.38, PrKit.Ff6.SnesAtbRules.Rate(30, false, 2, false, false), 0.01, "a Speed 30 character: 17.38 %/s (plan_atb.md)");
            Eq(90 * 81 >> 4, PrKit.Ff6.SnesAtbRules.AtbAdd(30, false, 2, true, false), "with Haste: 90");
            Eq(60 * 81 >> 4, PrKit.Ff6.SnesAtbRules.AtbAdd(30, false, 2, true, true), "Slow wins: 60");
            Eq(50 * 112 >> 4, PrKit.Ff6.SnesAtbRules.AtbAdd(30, true, 2, false, false), "a Speed 30 monster: (30 + 20) x (75 + 37) / 16 = 350");
            Near(16.05, PrKit.Ff6.SnesAtbRules.Rate(30, true, 2, false, false), 0.01, "a Speed 30 monster: 16.05 %/s");
            Eq(PrKit.Ff6.SnesAtbRules.AtbAdd(30, true, 0, false, false), PrKit.Ff6.SnesAtbRules.AtbAdd(30, true, 5, false, false),
               "no battle-speed term for monsters");
            Eq(50 * 135 >> 4, PrKit.Ff6.SnesAtbRules.AtbAdd(30, true, 2, true, false), "a hasted monster: 90 + 45 = 135");
            Eq(50 * 90 >> 4, PrKit.Ff6.SnesAtbRules.AtbAdd(30, true, 2, false, true), "a slowed monster: 60 + 30 = 90");
            Eq((210 + 51 & 0xFF) * 75 >> 4, PrKit.Ff6.SnesAtbRules.AtbAdd(210, false, 2, false, false), "Speed + 51 is 8-bit (ADC), as on the SNES");
        }
        finally
        {
            PrKit.Ff6.SnesAtbRules.NormalK = nk; PrKit.Ff6.SnesAtbRules.HasteK = hk; PrKit.Ff6.SnesAtbRules.SlowK = sk;
            PrKit.Ff6.SnesAtbRules.CharBias = cb; PrKit.Ff6.SnesAtbRules.MonsterBias = mb;
            PrKit.Ff6.SnesAtbRules.MonsterBattleSpeed = mbs; PrKit.Ff6.SnesAtbRules.MonsterHalfMore = mhm;
        }
        Eq(336, PrKit.Ff6.SnesAtbRules.AtbAdd(50, true, 2, false, false), "vanilla's monster add again once put back");
        Eq(420, PrKit.Ff6.SnesAtbRules.AtbAdd(50, false, 2, false, false), "vanilla's character add again once put back");

        Eq(2, PrKit.Ff6.SnesAtbRules.QuickfillFactor(0), "Quickfill: no one waiting for a command, x2");
        Eq(1, PrKit.Ff6.SnesAtbRules.QuickfillFactor(1), "Quickfill: a turn up, x1");
        Eq(1, PrKit.Ff6.SnesAtbRules.QuickfillFactor(4), "Quickfill: all four up, x1");

        var hold = new PrKit.Ff6.TimeHold { GiveUp = 20f };
        Eq(false, hold.Update(false, 0f), "no action: time runs");
        Eq(true, hold.Update(true, 1f), "an action starts: time held");
        Eq(true, hold.Update(true, 3.5f), "still playing: held");
        Eq(false, hold.Update(false, 4f), "it ends: time runs");
        Eq(1, hold.Holds, "one hold");
        Near(3.0, hold.LastHeld, 1e-6, "held 3 s");
        Eq(true, hold.Update(true, 10f), "the next action: held");
        Eq(true, hold.Update(true, 30f), "20 s in: still held");
        Eq(false, hold.Update(true, 30.5f), "over 20 s: given up, time runs");
        Eq(false, hold.Update(true, 60f), "given up until that state ends");
        Eq(false, hold.Update(false, 61f), "it ends");
        Eq(true, hold.Update(true, 62f), "a new action is held again");
        _ = R;
    }

    static void AtbChants()
    {
        PrKit.Ff6.SnesAtbRules.Chant C(int type, int cmd, bool monster = false, bool manip = false, bool wild = false,
                                       bool rampage = false, bool dance = false, bool copied = false) =>
            PrKit.Ff6.SnesAtbRules.ChantOf(type, cmd, monster, manip, wild, rampage, dance, copied, out _);
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Landing, C(16, 1, monster: true), "Jump's landing, a monster's too");
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Game, C(1, 1, monster: true), "a monster's act: the game's");
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Game, C(1, 1, manip: true), "a manipulated act: the game's");
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Now, C(15, 1), "going up (Jump): at once");
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Now, C(1, 1, wild: true), "Berserk / Muddle: at once");
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Now, C(1, 1, rampage: true), "Rage: at once");
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Now, C(1, 22, dance: true), "a Dance: at once");
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Command, C(1, 22), "Dance chosen while not dancing: the table");
        PrKit.Ff6.SnesAtbRules.ChantOf(1, 7, false, false, false, false, false, false, out int magic);
        Eq(32, magic, "Magic waits $20");
        PrKit.Ff6.SnesAtbRules.ChantOf(1, 1, false, false, false, false, false, true, out int mimic);
        Eq(16, mimic, "a copied act waits Mimic's own ($10)");
        Eq(25, PrKit.Ff6.SnesAtbRules.WaitCommand(1, true), "a copied act's command is Mimic's");
        Eq(PrKit.Ff6.SnesAtbRules.Chant.Unknown, C(1, 99), "a command the table doesn't have");
    }

    // one fighter (slot 0) on a fake clock: SnesStatusRound frame by frame, the statuses fixed, ticks landing
    // at once; events: "step" (a status step), "Regen", "Sap", "Poison"
    static List<(double T, string Kind)> RunClock(double seconds, int step, PrKit.Ff6.SnesStatus s,
                                                  Func<int, int> addFilter = null, Func<PrKit.Ff6.SnesStatusClock, char, char> stepKind = null)
    {
        var c = new PrKit.Ff6.SnesStatusClock(step) { AddFilter = addFilter, StepKind = stepKind };
        var round = new PrKit.Ff6.SnesStatusRound();
        var rng = new Random(1);
        var ev = new List<(double, string)>();
        double t = 0, frame = 1 / PrKit.Ff6.SnesStatusClock.FramesPerSecond;
        while (t < seconds)
        {
            t += frame;
            round.Advance(frame, slot => { if (slot == 0 && c.Visit(s, rng)) ev.Add((t, "step")); });
            if (c.DueRegen) { c.DueRegen = false; ev.Add((t, "Regen")); }
            if (c.DueSap) { c.DueSap = false; ev.Add((t, "Sap")); }
            if (c.DuePoison) { c.DuePoison = false; ev.Add((t, "Poison")); }
        }
        return ev;
    }

    static List<double> Gaps(List<(double T, string Kind)> ev, string kind)
    {
        var ts = ev.Where(x => x.Kind == kind).Select(x => x.T).ToList();
        return ts.Zip(ts.Skip(1), (a, b) => b - a).ToList();
    }

    static double MeanGap(List<(double T, string Kind)> ev, string kind)
    {
        var g = Gaps(ev, kind);
        if (g.Count < 5) throw new Exception($"only {g.Count + 1} {kind} events");
        return g.Average();
    }

    static void EveryGap(List<(double T, string Kind)> ev, string kind, double want, string what)
    {
        var g = Gaps(ev, kind);
        if (g.Count < 5 || g.Any(x => Math.Abs(x - want) > 0.02))
            throw new Exception($"{what}: want every {want:0.000} s, got {string.Join(" ", g.Take(8).Select(x => x.ToString("0.000")))}");
    }

    const PrKit.Ff6.SnesStatus Po = PrKit.Ff6.SnesStatus.Poison, Re = PrKit.Ff6.SnesStatus.Regen, Sa = PrKit.Ff6.SnesStatus.Sap,
                               Ha = PrKit.Ff6.SnesStatus.Haste, Sl = PrKit.Ff6.SnesStatus.Slow, St = PrKit.Ff6.SnesStatus.Stop;

    static void StatusClockTimes()
    {
        Eq(64, PrKit.Ff6.SnesStatusClock.AddNormal, "vanilla's add");
        Eq(84, PrKit.Ff6.SnesStatusClock.AddHaste, "vanilla's Haste add");
        Eq(32, PrKit.Ff6.SnesStatusClock.AddSlow, "vanilla's Slow add");
        Eq((18, 18, 26, 34), (PrKit.Ff6.SnesStatusClock.SleepSteps, PrKit.Ff6.SnesStatusClock.StopSteps,
                              PrKit.Ff6.SnesStatusClock.ReflectSteps, PrKit.Ff6.SnesStatusClock.FreezeSteps), "vanilla's timers");
        var normal = RunClock(200, 0, Po | Re);
        EveryGap(normal, "step", 2.130, "a status step (128 frames)");
        EveryGap(normal, "Regen", 8.519, "Regen (512 frames)");
        EveryGap(normal, "Poison", 17.039, "Poison (1024 frames)");
        EveryGap(RunClock(100, 0, Re | Sa), "Sap", 8.519, "Sap (Regen's flag, C2/5B74)");
        Near(6.487, MeanGap(RunClock(400, 0, Ha | Po | Re), "Regen"), 0.01, "Haste's Regen, on average (12-13 visits)");
        EveryGap(RunClock(300, 0, Sl | Re), "Regen", 2 * 8.519, "Slow's Regen");
        // a mod's own add (T-Edition: AddHaste 96) takes, and goes back
        int was = PrKit.Ff6.SnesStatusClock.AddHaste;
        try
        {
            PrKit.Ff6.SnesStatusClock.AddHaste = 96;
            Near(4 * 256.0 / 96 * 32 / PrKit.Ff6.SnesStatusClock.FramesPerSecond, MeanGap(RunClock(400, 0, Ha | Re), "Regen"), 0.02, "T-Edition's Haste add");
        }
        finally { PrKit.Ff6.SnesStatusClock.AddHaste = was; }
    }

    // bc-junction's rules (Beyond Chaos) through the clock's hooks; with none, nothing changes (WC, vanilla)
    static void StatusClockHooks()
    {
        string Run(Func<int, int> f, Func<PrKit.Ff6.SnesStatusClock, char, char> kind, PrKit.Ff6.SnesStatus s) =>
            string.Join(";", RunClock(120, 3, s, f, kind).Select(x => $"{x.T:0.0000}{x.Kind}"));
        Eq(Run(null, null, Po | Re), Run(a => a, (c, k) => k, Po | Re), "hooks that change nothing: the same events");
        double fps = PrKit.Ff6.SnesStatusClock.FramesPerSecond;
        // Time Font (x1.25: 64 -> 80) and Time Sink (x0.75: 64 -> 48) on the add; Regen is 4 steps
        Near(4 * 256.0 / 80 * 32 / fps, MeanGap(RunClock(400, 0, Re, a => Math.Min(255, a * 5 / 4)), "Regen"), 0.02, "Time Font's Regen");
        Near(4 * 256.0 / 48 * 32 / fps, MeanGap(RunClock(400, 0, Re, a => Math.Min(255, a * 3 / 4)), "Regen"), 0.02, "Time Sink's Regen");
        Eq(Run(a => 255, null, Re), Run(a => 1000, null, Re), "the add is kept to 255 (a byte)");
        Eq(0, RunClock(60, 0, Re, a => -5).Count, "an add under 0 is 0: no steps");

        // the ticks each step sends: step m's send carries the kind step m-1 read from the table (C2/5AD6)
        Dictionary<int, string> Sends(List<(double T, string Kind)> ev)
        {
            var sends = new Dictionary<int, string>();
            int m = 0;
            foreach (var e in ev)
                if (e.Kind == "step") m++;
                else sends[m] = sends.TryGetValue(m, out var was) ? was + "+" + e.Kind : e.Kind;
            return sends;
        }
        // a forced 'P' at one step whose table kind is 'R': Poison at the next step's send, and that Regen never comes
        int n = 0, forcedAt = -1;
        var natural = Sends(RunClock(60, 0, Po | Re));
        var forced = Sends(RunClock(60, 0, Po | Re, null, (c, k) =>
        {
            n++;
            if (forcedAt < 0 && n > 8 && k == 'R') { forcedAt = n; return 'P'; }
            return k;
        }));
        Eq(true, forcedAt > 0, "a step with the table's 'R' to force");
        Eq("Regen", natural.GetValueOrDefault(forcedAt + 1), $"without the hook, step {forcedAt + 1} sends the table's Regen");
        Eq("Poison", forced.GetValueOrDefault(forcedAt + 1), $"a 'P' forced at step {forcedAt}: Poison at step {forcedAt + 1}'s send, in place of Regen");
        Eq(natural.GetValueOrDefault(forcedAt), forced.GetValueOrDefault(forcedAt), "the forcing step's own send unchanged");
        // Miasma every step (the kind 'P' for a Poisoned fighter) and Regenerator every step ('R'): a tick every step,
        // the other kind's table slots lost
        EveryGap(RunClock(100, 0, Po | Re, null, (c, k) => (c.Statuses & Po) != 0 ? 'P' : k), "Poison", 128 / fps, "Miasma every step: Poison every step");
        Eq(0, RunClock(100, 0, Po | Re, null, (c, k) => 'P').Count(x => x.Kind == "Regen"), "Miasma every step: the Regen slots lost");
        EveryGap(RunClock(100, 0, Po | Re, null, (c, k) => 'R'), "Regen", 128 / fps, "Regenerator every step: Regen every step");
        Eq(0, RunClock(100, 0, Po | Re, null, (c, k) => 'R').Count(x => x.Kind == "Poison"), "Regenerator every step: the Poison slot lost");
        // once a step, the step index moving on as usual, never while stopped
        int calls = 0;
        var steps = new List<int>();
        var ev = RunClock(60, 5, Re, null, (c, k) => { calls++; steps.Add(c.Step); return k; });
        Eq(ev.Count(x => x.Kind == "step"), calls, "StepKind once a step");
        Eq(true, steps.Count > 10 && steps.Zip(steps.Skip(1), (x, y) => y == ((x + 1) & 0xFF)).All(b => b), "the step index moves on as usual");
        calls = 0;
        RunClock(60, 0, Re | St, null, (c, k) => { calls++; return k; });
        Eq(0, calls, "no StepKind while stopped");
    }
}
