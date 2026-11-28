using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Xml.Linq;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Tests;

/// <summary>1.4.0: SMS, contacts and the Stream Deck (windows/PROTOCOL-SMS.md, ZIGMon 5.59.4).</summary>
public class SmsParserTests
{
    private static JsonDocument Doc(string json) => ProtocolParser.ParseDocument(Encoding.UTF8.GetBytes(json));

    private const string HelloBase = "\"ok\":true,\"api\":1,\"server\":\"zigmon\",\"version\":\"5.59.4\",\"house\":\"mqtt\",\"boot\":\"ab12\",\"seq\":3";

    [Fact]
    public void HelloSmsIsRead()
    {
        using var d = Doc("{" + HelloBase + ",\"sms\":{\"read\":true,\"send\":true,\"contacts\":false,\"ready\":true}}");
        var h = ProtocolParser.Hello(d.RootElement);
        Assert.Equal(new SmsPermissions(true, true, false, true), h.Sms);
        Assert.True(h.Sms.CanSend);
        Assert.True(h.Sms.Any);
    }

    [Theory]
    [InlineData("")]                                    // a ZIGMon before 5.59.4
    [InlineData(",\"sms\":null")]
    [InlineData(",\"sms\":true")]
    [InlineData(",\"sms\":{\"read\":\"yes\",\"send\":1}")] // wrong types are no
    public void OlderOrOddHelloAllowsNothing(string extra)
    {
        using var d = Doc("{" + HelloBase + extra + "}");
        var h = ProtocolParser.Hello(d.RootElement);
        Assert.False(h.Sms.Any);
        Assert.False(h.Sms.CanSend);
        Assert.False(h.Sms.Contacts);
    }

    [Fact]
    public void SendWithoutAGatewayIsNotOffered()
    {
        Assert.False(new SmsPermissions(true, true, true, false).CanSend);
    }

    private static WaitResult Wait(string events) =>
        ProtocolParser.Wait(Doc("{\"ok\":true,\"boot\":\"ab12\",\"seq\":900,\"reset\":false,\"events\":[" + events + "]}").RootElement);

    [Fact]
    public void AnSmsEventAsTheContractShowsIt()
    {
        var w = Wait("{\"seq\":812,\"at\":1764340000.1,\"kind\":\"sms\",\"device\":\"sms\",\"key\":\"in\",\"active\":true,\"what\":\"sms\","
            + "\"sms\":{\"id\":\"s_19ab\",\"from\":\"+420777123456\",\"contact\":{\"id\":\"c_5f2a9e\",\"name\":\"Jana Nováková\"},"
            + "\"text\":\"Ahoj,\\r\\nbudu tam v 6.\",\"at\":1764340000}}");
        var e = Assert.Single(w.Events);
        Assert.Equal(SensorKinds.Sms, e.Kind);
        Assert.NotNull(e.Sms);
        Assert.Equal("s_19ab", e.Sms!.Id);
        Assert.True(e.Sms.Incoming);
        Assert.Equal("+420777123456", e.Sms.Number);
        Assert.Equal("c_5f2a9e", e.Sms.Contact!.Id);
        Assert.Equal("Jana Nováková", e.Sms.Who);
        Assert.Equal("Ahoj,\nbudu tam v 6.", e.Sms.Text);
        Assert.Equal(DateTimeOffset.FromUnixTimeSeconds(1764340000), e.Sms.At);
        // not a sensor: nothing watches it, so it can never become a sensor alert
        Assert.Equal(AlertDecision.NotWatched, AlertFilter.Decide(new NotifierSettings(), e, DateTimeOffset.UtcNow));
    }

    [Fact]
    public void SmsTextIsCleanedAndCapped()
    {
        string evil = "Pay\u202Enow\u200B\u0007 \n\n\n\nthen" + new string('x', 9000);
        var w = Wait("{\"seq\":5,\"kind\":\"sms\",\"device\":\"sms\",\"key\":\"in\",\"sms\":{\"id\":\"s_1\",\"from\":\"777 123 456\",\"text\":"
            + JsonSerializer.Serialize(evil) + ",\"contact\":{\"id\":\"<script>\",\"name\":\"\\u202Eevil\"}}}");
        var m = Assert.Single(w.Events).Sms!;
        Assert.StartsWith("Paynow\n\nthen", m.Text);
        Assert.DoesNotContain('\u202E', m.Text);
        Assert.True(m.Text.Length <= ProtocolParser.SmsTextMax);
        Assert.EndsWith("…", m.Text);
        Assert.Equal("777123456", m.Number);
        Assert.Equal("", m.Contact!.Id);       // not an id ZIGMon makes
        Assert.Equal("evil", m.Contact.Name);
    }

    [Theory]
    [InlineData("{\"seq\":5,\"kind\":\"sms\",\"device\":\"sms\"}")]                                     // no sms object
    [InlineData("{\"seq\":5,\"kind\":\"sms\",\"device\":\"sms\",\"sms\":\"hi\"}")]
    [InlineData("{\"seq\":5,\"kind\":\"sms\",\"device\":\"sms\",\"sms\":{\"from\":\"call me\",\"text\":\"\"}}")]
    [InlineData("{\"seq\":5,\"kind\":\"deck\",\"device\":\"deck\",\"key\":\"sms\",\"what\":\"format-disk\"}")]
    [InlineData("{\"seq\":5,\"kind\":\"deck\",\"device\":\"deck\",\"key\":\"light\",\"what\":\"last\"}")]
    public void BrokenSmsAndDeckEventsAreDropped(string ev)
    {
        Assert.Empty(Wait(ev).Events);
    }

    [Fact]
    public void ADeckComposeEvent()
    {
        var w = Wait("{\"seq\":813,\"kind\":\"deck\",\"device\":\"deck\",\"key\":\"sms\",\"active\":true,\"what\":\"compose\","
            + "\"deck\":{\"install\":\"inst_9\",\"computer\":\"OFFICE-PC\",\"to\":["
            + "{\"id\":\"c_5f2a9e\",\"name\":\"Jana Nováková\",\"number\":\"+420777123456\"},"
            + "{\"id\":\"\",\"name\":\"\",\"number\":\"+420 602 111 222\"},"
            + "{\"id\":\"c_5f2a9e\",\"name\":\"Jana again\",\"number\":\"00420777123456\"},"   // the same phone: once
            + "{\"name\":\"no number\"},\"junk\"]}}");
        var e = Assert.Single(w.Events);
        Assert.Equal(SensorKinds.Deck, e.Kind);
        Assert.Equal(DeckAsk.Compose, e.Deck!.What);
        Assert.Equal("OFFICE-PC", e.Deck.Computer);
        Assert.Equal(2, e.Deck.To.Count);
        Assert.Equal("c_5f2a9e", e.Deck.To[0].Id);
        Assert.Equal("+420602111222", e.Deck.To[1].Number);
        Assert.Equal(AlertDecision.NotWatched, AlertFilter.Decide(new NotifierSettings(), e, DateTimeOffset.UtcNow));
    }

    [Fact]
    public void ADeckLastEventAndAtMostTwentyRecipients()
    {
        var w = Wait("{\"seq\":9,\"kind\":\"deck\",\"device\":\"deck\",\"key\":\"sms\",\"what\":\"last\"}");
        Assert.Equal(DeckAsk.Last, Assert.Single(w.Events).Deck!.What);

        string many = string.Join(",", Enumerable.Range(100, 40).Select(i => "{\"number\":\"+420777123" + i + "\"}"));
        var w2 = Wait("{\"seq\":9,\"kind\":\"deck\",\"device\":\"deck\",\"key\":\"sms\",\"what\":\"compose\",\"deck\":{\"to\":[" + many + "]}}");
        Assert.Equal(ProtocolParser.MaxDeckTo, w2.Events[0].Deck!.To.Count);
    }

    [Fact]
    public void SensorEventsStillWorkBesideThem()
    {
        var w = Wait("{\"seq\":4,\"kind\":\"motion\",\"device\":\"0xa1\",\"name\":\"PIR\",\"active\":true,\"what\":\"motion\"},"
            + "{\"seq\":5,\"kind\":\"sms\",\"device\":\"sms\",\"sms\":{\"id\":\"s_2\",\"from\":\"+420777000111\",\"text\":\"hi\"}}");
        Assert.Equal(2, w.Events.Count);
        Assert.Equal(SensorKinds.Motion, w.Events[0].Kind);
        Assert.Null(w.Events[0].Sms);
        Assert.Equal(SensorKinds.Sms, w.Events[1].Kind);
    }

    [Fact]
    public void SmsListNewestFirstAndChecked()
    {
        using var d = Doc("{\"ok\":true,\"messages\":["
            + "{\"id\":\"s_1\",\"dir\":\"in\",\"number\":\"+420777123456\",\"contact\":null,\"text\":\"first\",\"at\":1764340000,\"ok\":true},"
            + "{\"id\":\"s_2\",\"dir\":\"out\",\"number\":\"+420777123456\",\"contact\":{\"id\":\"c_5f2a9e\",\"name\":\"Jana\"},\"text\":\"second\",\"at\":1764340100,\"ok\":false},"
            + "{\"id\":\"s_2\",\"dir\":\"out\",\"number\":\"+420777123456\",\"text\":\"dup\",\"at\":1764340100},"
            + "7, null, {\"dir\":\"sideways\",\"number\":\"x\",\"text\":\"\"}]}");
        var list = ProtocolParser.SmsList(d.RootElement);
        Assert.Equal(new[] { "s_2", "s_1" }, list.Select(m => m.Id));
        Assert.False(list[0].Incoming);
        Assert.False(list[0].Ok);
        Assert.True(list[1].Incoming);
    }

    [Fact]
    public void ContactsAreCheckedFieldByField()
    {
        string json = "{\"ok\":true,\"contacts\":["
            + "{\"id\":\"c_5f2a9e\",\"name\":\"Jana Nováková\",\"numbers\":[{\"label\":\"mobile\",\"number\":\"+420 777 123 456\"},{\"label\":\"work\",\"number\":\"+420602111222\"}],\"group\":\"Family\",\"note\":\"\",\"favourite\":true},"
            + "{\"id\":\"c_ZZZ\",\"name\":\"Bad id\",\"numbers\":[{\"number\":\"+420602000000\"}]},"
            + "{\"id\":\"c_aaaaaa\",\"name\":\"No numbers\",\"numbers\":[]},"
            + "{\"id\":\"c_bbbbbb\",\"name\":\"Petr\",\"numbers\":[{\"label\":\"" + new string('L', 50) + "\",\"number\":\"603123456\"}],\"group\":\"Work\"},"
            + "{\"id\":\"c_5f2a9e\",\"name\":\"Same id\",\"numbers\":[{\"number\":\"+420602000001\"}]}"
            + "],\"groups\":[\"Family\",\"family\",7]}";
        using var d = Doc(json);
        var book = ProtocolParser.Contacts(d.RootElement);
        Assert.Equal(new[] { "Jana Nováková", "Petr" }, book.Contacts.Select(c => c.Name));
        Assert.Equal("+420777123456", book.Contacts[0].Numbers[0].Number);
        Assert.True(book.Contacts[0].Favourite);
        Assert.True(book.Contacts[1].Numbers[0].Label.Length <= 20);
        Assert.Equal(new[] { "Family", "Work" }, book.Groups);
        Assert.Same(book.Contacts[0], book.ByNumber("00420777123456"));
    }

    [Fact]
    public void SendResultWords()
    {
        using var ok = Doc("{\"ok\":true,\"sent\":[\"+420777123456\",\"+420602111222\"],\"failed\":[],\"message\":\"2 sent\",\"error\":null}");
        var r = ProtocolParser.SendResult(ok.RootElement);
        Assert.True(r.Ok);
        Assert.Equal(2, r.Sent);
        Assert.Equal("2 sent", r.Message);
        using var no = Doc("{\"ok\":false,\"sent\":[],\"failed\":[\"+420777123456\"],\"error\":\"the daily limit of 20 SMS is reached\"}");
        var n = ProtocolParser.SendResult(no.RootElement);
        Assert.False(n.Ok);
        Assert.Equal(1, n.Failed);
        Assert.Equal("the daily limit of 20 SMS is reached", n.Message);
    }
}

public class SmsCounterTests
{
    [Theory]
    [InlineData("", 0, 0, false)]
    [InlineData("Hello", 5, 1, false)]
    [InlineData("{x}", 5, 1, false)]               // the escape characters count two
    [InlineData("Ahoj, jak se máš?", 17, 1, true)]  // á: the whole text is UCS-2
    [InlineData("👍", 2, 1, true)]                  // past the first plane: two units
    public void CountsUnits(string text, int units, int parts, bool unicode)
    {
        var c = SmsCounter.Count(text);
        Assert.Equal(units, c.Units);
        Assert.Equal(parts, c.Parts);
        Assert.Equal(unicode, c.Unicode);
    }

    [Theory]
    [InlineData(160, 1)]
    [InlineData(161, 2)]
    [InlineData(306, 2)]
    [InlineData(307, 3)]
    [InlineData(459, 3)]
    public void Gsm7Parts(int length, int parts)
    {
        var c = SmsCounter.Count(new string('a', length));
        Assert.Equal(parts, c.Parts);
        Assert.False(c.Unicode);
        Assert.Equal(parts == 1 ? 160 : 153, c.PerPart);
    }

    [Theory]
    [InlineData(70, 1)]
    [InlineData(71, 2)]
    [InlineData(134, 2)]
    [InlineData(135, 3)]
    public void Ucs2Parts(int length, int parts)
    {
        var c = SmsCounter.Count(new string('č', length));
        Assert.Equal(parts, c.Parts);
        Assert.True(c.Unicode);
        Assert.Equal(parts == 1 ? 70 : 67, c.PerPart);
    }

    [Fact]
    public void TheCounterSpeaksPlainly()
    {
        Assert.Equal("5 / 160 · 1 SMS", SmsCounter.Count("Hello").Text);
        Assert.Equal(155, SmsCounter.Count("Hello").Left);
        Assert.Equal("170 / 306 · 2 SMS", SmsCounter.Count(new string('a', 170)).Text);
        Assert.Equal("Unicode · 3 / 70 · 1 SMS", SmsCounter.Count("čau").Text);
    }
}

public class RecipientTests
{
    private static readonly ContactBook Book = new(new[]
    {
        new Contact("c_5f2a9e", "Jana Nováková", new[] { new ContactNumber("mobile", "+420777123456") }, "Family", "", true),
        new Contact("c_bbbbbb", "Petr Svoboda", new[] { new ContactNumber("mobile", "+420603123456"), new ContactNumber("work", "+420222333444") }, "Work", "", false),
        new Contact("c_cccccc", "Babička", new[] { new ContactNumber("", "+420604000111") }, "Family", "", false),
    }, new[] { "Family", "Work" });

    [Theory]
    [InlineData("+420 777 123 456", "+420777123456")]
    [InlineData("777-123-456", "777123456")]
    [InlineData("(0420) 777.123.456", "0420777123456")]
    [InlineData("12", "")]               // too short
    [InlineData("+4207771234567890123456", "")]
    [InlineData("777 12x 456", "")]
    [InlineData("4+20", "")]             // + only first
    public void NumbersAreCleaned(string typed, string clean)
    {
        Assert.Equal(clean, SmsNumbers.Clean(typed));
    }

    [Fact]
    public void TheSamePhoneComparesEqual()
    {
        Assert.Equal(SmsNumbers.Key("+420777123456"), SmsNumbers.Key("00420 777 123 456"));
        Assert.Equal("…456", SmsNumbers.Masked("+420777123456"));
    }

    [Fact]
    public void ATypedListBecomesChips()
    {
        var (chips, bad) = Recipients.Parse("+420 602 999 888, jana novakova; Family\nnobody here, 777123456, +420602999888", Book);
        Assert.Equal(new[] { "+420602999888", "contact:c_5f2a9e", "group:Family", "777123456" }, chips.Select(c => c.Wire));
        Assert.Equal(new[] { "nobody here" }, bad);
        Assert.Equal(RecipientKind.Group, chips[2].Kind);
        Assert.Equal("Group · 2 contacts", chips[2].Detail);
    }

    [Fact]
    public void ANumberOfAContactIsNamed()
    {
        var r = Recipients.Resolve("00420777123456", Book)!;
        Assert.Equal(RecipientKind.Number, r.Kind);
        Assert.Equal("Jana Nováková", r.Title);
    }

    [Fact]
    public void WireFormsAreChecked()
    {
        Assert.True(Recipients.IsWire("+420777123456"));
        Assert.True(Recipients.IsWire("contact:c_5f2a9e"));
        Assert.True(Recipients.IsWire("group:Family"));
        Assert.False(Recipients.IsWire("contact:../../etc"));
        Assert.False(Recipients.IsWire("group:"));
        Assert.False(Recipients.IsWire("group:\u202Eevil"));
        Assert.False(Recipients.IsWire("+420 777 123 456")); // the wire form is the clean one
        Assert.False(Recipients.IsWire("jana"));
        var wire = Recipients.ToWire(Enumerable.Range(0, 30).Select(i => Recipient.ForNumber("+42077712" + (3000 + i))).Append(Recipient.ForNumber("+420777123000")));
        Assert.Equal(Recipients.MaxRecipients, wire.Count);
    }

    [Fact]
    public void SuggestionsFindNamesNumbersAndGroups()
    {
        Assert.Equal("Jana Nováková", Recipients.Suggest("nov", Book)[0].Title);       // accents ignored
        Assert.Equal("Babička", Recipients.Suggest("babic", Book)[0].Title);
        var petr = Recipients.Suggest("svo", Book);
        Assert.Equal(2, petr.Count);                                                  // once per number
        Assert.All(petr, p => Assert.Equal(RecipientKind.Number, p.Kind));
        Assert.Contains(Recipients.Suggest("6031", Book), r => r.Title == "Petr Svoboda");
        Assert.Contains(Recipients.Suggest("fam", Book), r => r.Wire == "group:Family");
        var typed = Recipients.Suggest("+420 999 888 777", Book);
        Assert.Equal("+420999888777", typed[0].Wire);                                  // a raw number is offered as it is
        Assert.Equal(new[] { "Jana Nováková" }, Recipients.Suggest("", Book).Select(r => r.Title)); // favourites as quick chips
    }

    [Fact]
    public void FavouritesComeFirst()
    {
        var both = new ContactBook(new[]
        {
            new Contact("c_000001", "Anna A", new[] { new ContactNumber("", "+420700000001") }, "", "", false),
            new Contact("c_000002", "Anna B", new[] { new ContactNumber("", "+420700000002") }, "", "", true),
        }, Array.Empty<string>());
        Assert.Equal("Anna B", Recipients.Suggest("anna", both)[0].Title);
    }

    [Fact]
    public void ConversationsGroupByContactThenNumber()
    {
        var t0 = DateTimeOffset.FromUnixTimeSeconds(1764340000);
        var msgs = new[]
        {
            new SmsMessage("s_1", true, "+420777123456", new SmsContactRef("c_5f2a9e", "Jana"), "a", t0, null),
            new SmsMessage("s_2", false, "+420777123456", new SmsContactRef("c_5f2a9e", "Jana"), "b", t0.AddMinutes(1), true),
            new SmsMessage("s_3", true, "00420602111222", null, "c", t0.AddMinutes(5), null),
            new SmsMessage("s_4", true, "+420602111222", null, "d", t0.AddMinutes(2), null),
            new SmsMessage("s_4", true, "+420602111222", null, "d again", t0.AddMinutes(2), null),
        };
        var threads = SmsThreads.Group(msgs);
        Assert.Equal(2, threads.Count);
        Assert.Equal("00420602111222", threads[0].Number);                 // newest conversation first
        Assert.Equal(new[] { "d", "c" }, threads[0].Messages.Select(m => m.Text)); // oldest first inside
        Assert.Equal("Jana", threads[1].Title);
        Assert.Equal("c_5f2a9e", threads[1].ContactId);
    }

    [Theory]
    [InlineData("Jana Nováková", "JN")]
    [InlineData("jana", "J")]
    [InlineData("Ing. Petr  van Svoboda", "IS")]
    [InlineData("+420777123456", "")]
    [InlineData("", "")]
    [InlineData("Čeněk Šťastný", "ČŠ")]
    public void AvatarInitials(string name, string initials)
    {
        Assert.Equal(initials, Avatars.Initials(name));
    }

    [Fact]
    public void AvatarColourIsStable()
    {
        Assert.Equal(Avatars.Accent("contact:c_5f2a9e"), Avatars.Accent("contact:c_5f2a9e"));
        Assert.StartsWith("#", Avatars.Accent(null));
    }
}

public class SmsClientTests
{
    private static FakeZigmon Fake()
    {
        var f = new FakeZigmon { HelloSms = new { read = true, send = true, contacts = true, ready = true } };
        f.SmsMessages.Add(new { id = "s_2", dir = "out", number = "+420777123456", contact = new { id = "c_5f2a9e", name = "Jana" }, text = "ok", at = 1764340100, ok = true });
        f.SmsMessages.Add(new { id = "s_1", dir = "in", number = "+420777123456", contact = new { id = "c_5f2a9e", name = "Jana" }, text = "hi?", at = 1764340000, ok = true });
        f.ContactsJson = "{\"ok\":true,\"contacts\":[{\"id\":\"c_5f2a9e\",\"name\":\"Jana\",\"numbers\":[{\"label\":\"mobile\",\"number\":\"+420777123456\"}],\"group\":\"Family\",\"note\":\"\",\"favourite\":true}],\"groups\":[\"Family\"]}";
        return f;
    }

    [Fact]
    public async Task HelloCarriesThePermissions()
    {
        var fake = Fake();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        Assert.True((await c.HelloAsync(default)).Sms.CanSend);
        fake.HelloSms = null;
        Assert.False((await c.HelloAsync(default)).Sms.Any);
    }

    [Fact]
    public async Task GetSms()
    {
        var fake = Fake();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var list = await c.GetSmsAsync(50, default);
        Assert.Equal(new[] { "s_2", "s_1" }, list.Select(m => m.Id));
        var r = fake.Requests.Last();
        Assert.Contains("api=notifier&do=sms&limit=50", r.Uri.Query);
        Assert.Equal(FakeZigmon.GoodKey, r.Headers[AppInfo.KeyHeader]);
        await c.GetSmsAsync(100000, default);
        Assert.Contains("limit=200", fake.Requests.Last().Uri.Query);
    }

    [Fact]
    public async Task GetContacts()
    {
        var fake = Fake();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var book = await c.GetContactsAsync(default);
        Assert.Equal("Jana", Assert.Single(book.Contacts).Name);
        Assert.Contains("do=contacts", fake.Requests.Last().Uri.Query);
        fake.ContactsJson = null;
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.GetContactsAsync(default));
        Assert.Equal(403, e.Status);
    }

    [Fact]
    public async Task SendPostsJsonInTheContractsShape()
    {
        var fake = Fake();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var r = await c.SendSmsAsync(new[] { "contact:c_5f2a9e", "group:Family", "+420602111222", "not a number", "+420602111222" },
            "Ahoj 👋\r\nzítra", "s_1", default);
        Assert.True(r.Ok);
        Assert.Equal("POST", fake.Methods.Last());
        Assert.StartsWith("application/json", fake.ContentTypes.Last());
        var req = fake.Requests.Last();
        Assert.Contains("api=notifier&do=sms-send", req.Uri.Query);
        Assert.Equal(FakeZigmon.GoodKey, req.Headers[AppInfo.KeyHeader]);
        Assert.DoesNotContain("zítra", req.Uri.ToString());
        using var body = JsonDocument.Parse(fake.SentBodies.Single());
        Assert.Equal(new[] { "contact:c_5f2a9e", "group:Family", "+420602111222" }, body.RootElement.GetProperty("to").EnumerateArray().Select(x => x.GetString()));
        Assert.Equal("Ahoj 👋\nzítra", body.RootElement.GetProperty("text").GetString());
        Assert.Equal("s_1", body.RootElement.GetProperty("reply_to").GetString());
    }

    [Fact]
    public async Task NoReplyToWhenNotAReply()
    {
        var fake = Fake();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        await c.SendSmsAsync(new[] { "+420602111222" }, "hi", null, default);
        using var body = JsonDocument.Parse(fake.SentBodies.Single());
        Assert.False(body.RootElement.TryGetProperty("reply_to", out _));
    }

    [Fact]
    public async Task NothingIsSentThatCannotBe()
    {
        var fake = Fake();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        Assert.False((await c.SendSmsAsync(Array.Empty<string>(), "hi", null, default)).Ok);
        Assert.False((await c.SendSmsAsync(new[] { "jana" }, "hi", null, default)).Ok);
        Assert.False((await c.SendSmsAsync(new[] { "+420602111222" }, "   ", null, default)).Ok);
        Assert.False((await c.SendSmsAsync(new[] { "+420602111222" }, new string('a', SmsCounter.MaxText + 1), null, default)).Ok);
        Assert.Empty(fake.SentBodies);
    }

    [Theory]
    [InlineData(429, "{\"ok\":false,\"error\":\"the hourly limit of 10 SMS is reached\"}", "the hourly limit of 10 SMS is reached")]
    [InlineData(400, "{\"ok\":false,\"error\":\"the text is longer than ZIGMon sends (6 parts)\"}", "the text is longer than ZIGMon sends (6 parts)")]
    [InlineData(403, "{\"ok\":false,\"error\":\"this key may not send SMS\"}", "this key may not send SMS")]
    [InlineData(503, "{\"ok\":false,\"error\":\"the SMS gateway is not set up\"}", "the SMS gateway is not set up")]
    [InlineData(200, "{\"ok\":false,\"sent\":[],\"failed\":[\"+420602111222\"],\"error\":\"nothing could be sent\"}", "nothing could be sent")]
    public async Task ZigmonsLimitsComeBackInItsWords(int status, string answer, string words)
    {
        var fake = Fake();
        fake.SendAnswer = _ => (status, answer);
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var r = await c.SendSmsAsync(new[] { "+420602111222" }, "hi", null, default);
        Assert.False(r.Ok);
        Assert.Equal(words, r.Message);
    }

    [Fact]
    public async Task AWrongKeyStillThrowsAndTheKeyIsScrubbed()
    {
        var fake = Fake();
        fake.SendAnswer = _ => (429, "{\"ok\":false,\"error\":\"slow down " + FakeZigmon.GoodKey + "\"}");
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var r = await c.SendSmsAsync(new[] { "+420602111222" }, "hi", null, default);
        Assert.DoesNotContain(FakeZigmon.GoodKey[4..], r.Message);

        using var wrong = new ZigmonClient(K.Address, K.Wrong, Fake());
        var e = await Assert.ThrowsAsync<ZigmonException>(() => wrong.SendSmsAsync(new[] { "+420602111222" }, "hi", null, default));
        Assert.Equal(ZigmonErrorKind.Unauthorized, e.Kind);
        Assert.DoesNotContain("hi", e.Message.Split(' '));
        Assert.DoesNotContain("602111222", e.Message);
    }

    [Fact]
    public async Task AnOlderZigmonSaysNoWithoutBreakingAnything()
    {
        var fake = new FakeZigmon(); // no sms in hello; GET sms is "do must be ..."
        fake.Scripted.Enqueue((400, "{\"ok\":false,\"error\":\"do is hello, sensors, wait, update or download\"}", null));
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.GetSmsAsync(50, default));
        Assert.Equal(ZigmonErrorKind.BadRequest, e.Kind);
        Assert.False((await c.HelloAsync(default)).Sms.Any);
    }

    [Fact]
    public async Task TheServiceRaisesSmsAndDeckEvents()
    {
        var fake = Fake();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var svc = new NotifierService(c);
        var got = new List<TriggerEvent>();
        var two = new TaskCompletionSource();
        svc.EventsArrived += list => { lock (got) { got.AddRange(list); if (got.Count >= 2) two.TrySetResult(); } };
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        var run = svc.RunAsync(cts.Token);
        while (svc.Status.State != ConnectionState.Connected) await Task.Delay(10, cts.Token);
        Assert.True(svc.Status.Hello!.Sms.Read);
        fake.PushSms("s_9", "+420777123456", "Ahoj", new { id = "c_5f2a9e", name = "Jana" });
        fake.PushDeck("compose", new object[] { new { id = "c_5f2a9e", name = "Jana", number = "+420777123456" } });
        await two.Task.WaitAsync(cts.Token);
        cts.Cancel();
        await run;
        Assert.Equal("s_9", got[0].Sms!.Id);
        Assert.Equal("Jana", got[0].Sms!.Who);
        Assert.Equal("Jana", got[1].Deck!.To.Single().Name);
        Assert.Equal(3, svc.Sensors.Count); // the sensors are untouched
    }
}

public class SmsSettingsTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 28, 12, 0, 0, TimeSpan.Zero);

    [Fact]
    public void OnByDefault()
    {
        var s = new NotifierSettings();
        s.Sanitize(Now);
        Assert.True(s.SmsPopups);
        Assert.True(s.DeckPopups);
        Assert.True(s.SmsSound);
        Assert.Equal(AlarmSounds.DefaultId, s.SmsSoundId);
    }

    [Fact]
    public void RememberedAndReadBack()
    {
        var dir = Path.Combine(Path.GetTempPath(), "zn-" + Guid.NewGuid().ToString("N"));
        var store = new SettingsStore(Path.Combine(dir, "settings.json"));
        try
        {
            store.Save(new NotifierSettings { SmsPopups = false, DeckPopups = false, SmsSound = false, SmsSoundId = "doorbell" });
            var back = store.Load(Now);
            Assert.False(back.SmsPopups);
            Assert.False(back.DeckPopups);
            Assert.False(back.SmsSound);
            Assert.Equal("doorbell", back.SmsSoundId);
            string json = File.ReadAllText(store.Path);
            Assert.Contains("\"smsPopups\": false", json);
            Assert.Contains("\"deckPopups\": false", json);
        }
        finally
        {
            if (Directory.Exists(dir)) Directory.Delete(dir, true);
        }
    }

    [Fact]
    public void AnOlderSettingsFileTurnsThemOn()
    {
        var dir = Path.Combine(Path.GetTempPath(), "zn-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, "settings.json");
        try
        {
            File.WriteAllText(path, "{\"format\":1,\"sound\":true,\"smsSoundId\":\"file\"}");
            var s = new SettingsStore(path).Load(Now);
            Assert.True(s.SmsPopups && s.DeckPopups && s.SmsSound);
            Assert.Equal(AlarmSounds.DefaultId, s.SmsSoundId); // a file is not an SMS sound
        }
        finally
        {
            Directory.Delete(dir, true);
        }
    }

    [Fact]
    public void PausedAlertsHoldTheSmsPopupsBack()
    {
        var s = new NotifierSettings();
        Assert.True(s.ShowsSmsPopup(Now));
        s.PausedUntil = Now.AddMinutes(15);
        Assert.False(s.ShowsSmsPopup(Now));
        s.PausedUntil = null;
        s.SmsPopups = false;
        Assert.False(s.ShowsSmsPopup(Now));
    }
}

/// <summary>The XAML of the new windows, checked for what cannot be seen on Linux.</summary>
public class SmsXamlTests
{
    private static readonly XNamespace P = "http://schemas.microsoft.com/winfx/2006/xaml/presentation";
    private static readonly XNamespace X = "http://schemas.microsoft.com/winfx/2006/xaml";

    private static XDocument Xaml(string rel) => XDocument.Load(Path.Combine(ReleaseKeyTests.RepoRoot(), "windows", "ZigmonNotifier", rel));

    [Theory]
    [InlineData("Views/SmsWindow.xaml")]
    [InlineData("Views/MessagesWindow.xaml")]
    public void EveryStaticResourceIsInTheTheme(string file)
    {
        var theme = Xaml("Theme.xaml").Descendants().Select(e => (string?)e.Attribute(X + "Key")).Where(k => k is not null).ToHashSet();
        var doc = Xaml(file);
        var local = doc.Descendants().Select(e => (string?)e.Attribute(X + "Key")).Where(k => k is not null).ToHashSet();
        var used = doc.Descendants().SelectMany(e => e.Attributes()).Select(a => a.Value)
            .Where(v => v.StartsWith("{StaticResource ", StringComparison.Ordinal))
            .Select(v => v["{StaticResource ".Length..^1].Trim()).Distinct().ToList();
        Assert.NotEmpty(used);
        foreach (var k in used) Assert.True(theme.Contains(k) || local.Contains(k), file + " uses a resource nobody defines: " + k);
    }

    [Fact]
    public void TheSmsTextIsPlainTextInAScroller()
    {
        var doc = Xaml("Views/SmsWindow.xaml");
        var body = doc.Descendants(P + "TextBlock").Single(t => (string?)t.Attribute(X + "Name") == "Body");
        Assert.Equal("Wrap", (string?)body.Attribute("TextWrapping"));
        Assert.Equal(P + "StackPanel", body.Parent!.Name);
        Assert.Equal(P + "ScrollViewer", body.Parent!.Parent!.Name);
    }
}
