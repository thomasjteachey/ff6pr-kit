using System;
using System.Collections.Generic;
using System.Linq;
using PrKit;

// PrKit/SelfTests.cs on a fake clock (60 frames a second): discovery by name, selection, Wait/Until timing,
// timeouts, exceptions, fixtures. The [SelfTest] methods below are this test's own samples.
static class SelfTestsChecks
{
    static readonly List<string> order = new List<string>();
    static bool flag;
    static double flagAt = double.PositiveInfinity;   // the flag rises 1 s after demo.until starts

    [SelfTest("demo.wait")]
    static IEnumerable<TestStep> DemoWait(TestContext t)
    {
        double start = t.Now;
        yield return t.Wait(2.0);
        t.Check(t.Now - start >= 2.0 && t.Now - start < 2.05, $"waited {t.Now - start:0.000} s");
    }

    [SelfTest("demo.until")]
    static IEnumerable<TestStep> DemoUntil(TestContext t)
    {
        double start = t.Now;
        flagAt = start + 1.0;
        yield return t.Until(() => flag, 10, "the flag");
        t.Check(flag, "the flag is up");
        t.Check(t.Now - start >= 0.99, $"it came up after {t.Now - start:0.00} s");
    }

    [SelfTest("demo.timeout")]
    static IEnumerable<TestStep> DemoTimeout(TestContext t)
    {
        yield return t.Until(() => false, 0.5, "never");
        t.Check(true, "not reached");
    }

    [SelfTest("demo.throws")]
    static IEnumerable<TestStep> DemoThrows(TestContext t)
    {
        yield return t.Wait(0.1);
        throw new InvalidOperationException("boom");
    }

    [SelfTest("demo.fixture", Needs = "fx")]
    static IEnumerable<TestStep> DemoFixture(TestContext t)
    {
        order.Add("test");
        t.Check(order.SequenceEqual(new[] { "fixture", "test" }), "the fixture ran first");
        yield break;
    }

    [SelfTest("demo.nofixture", Needs = "missing")]
    static IEnumerable<TestStep> DemoNoFixture(TestContext t) { yield break; }

    [SelfTest("demo.slow", Timeout = 1)]
    static IEnumerable<TestStep> DemoSlow(TestContext t) { yield return t.Wait(5); }

    static void Eq<T>(T want, T got, string what)
    {
        if (!EqualityComparer<T>.Default.Equals(want, got)) throw new Exception($"{what}: want {want}, got {got}");
    }

    public static void Discovery()
    {
        var all = SelfTests.Discover(typeof(SelfTestsChecks).Assembly);
        Eq(7, all.Count(e => e.Name.StartsWith("demo.")), "the 7 samples found by name");
        Eq("fx", all.First(e => e.Name == "demo.fixture").Info.Needs, "Needs read");
        Eq(7, SelfTests.Select(all, "demo.*").Count, "a prefix");
        Eq(2, SelfTests.Select(all, "demo.wait, demo.until").Count, "names");
        Eq(all.Count, SelfTests.Select(all, "*").Count, "all");
        Eq(1, SelfTests.Select(all, "demo.wait,DEMO.WAIT").Count, "no test twice; names ignore case");
        try { SelfTests.Select(all, "demo.nope"); throw new Exception("an unknown name was accepted"); }
        catch (ArgumentException) { }
    }

    public static void Running()
    {
        order.Clear();
        flag = false;
        flagAt = double.PositiveInfinity;
        SelfTests.Fixtures["fx"] = FixtureSteps;
        var lines = new List<string>();
        var picked = SelfTests.Select(SelfTests.Discover(typeof(SelfTestsChecks).Assembly), "demo.*");
        SelfTests.Start(picked, lines.Add);
        double now = 0;
        int frames = 0;
        while (SelfTests.Update(now) && frames < 60 * 60)
        {
            frames++;
            now = frames / 60.0;
            if (now >= flagAt) flag = true;
        }
        Eq(true, SelfTests.Done, "all ran");
        var r = SelfTests.Results.ToDictionary(x => x.Name);
        Eq(7, r.Count, "7 results");
        Eq(true, r["demo.wait"].Passed && r["demo.wait"].Checks == 1, "Wait: 2 s of game time (" + string.Join(" | ", lines.Where(l => l.Contains("demo.wait"))) + ")");
        Eq(true, r["demo.until"].Passed && r["demo.until"].Checks == 2, "Until: polled until the flag (" + string.Join(" | ", lines.Where(l => l.Contains("demo.until"))) + ")");
        Eq("timed out: never", r["demo.timeout"].Error, "Until's own timeout");
        Eq(0, r["demo.timeout"].Checks, "a timed-out test stops there");
        Eq(true, r["demo.throws"].Error != null && r["demo.throws"].Error.Contains("InvalidOperationException: boom"), "an exception fails the test: " + r["demo.throws"].Error);
        Eq(true, r["demo.fixture"].Passed && r["demo.fixture"].Checks == 1, "a fixture's steps run first");
        Eq("no fixture 'missing' registered", r["demo.nofixture"].Error, "a missing fixture fails the test");
        Eq("timed out after 1 s", r["demo.slow"].Error, "the whole test's timeout");
        Eq(true, lines.Any(l => l == "[selftest] demo.wait pass (1 checks, 0 failed)"), "a summary line per test");
        Eq(true, lines.Any(l => l == "[selftest] FAIL demo.timeout: timed out: never"), "a FAIL line for a stopped test");
        Eq(true, SelfTests.Summary().StartsWith("selftest done: 3 passed, 4 failed [demo.nofixture (no fixture"), "the summary line: " + SelfTests.Summary());
        SelfTests.Fixtures.Remove("fx");
    }

    static IEnumerable<TestStep> FixtureSteps(TestContext t)
    {
        yield return t.Wait(0.05);
        order.Add("fixture");
    }
}
