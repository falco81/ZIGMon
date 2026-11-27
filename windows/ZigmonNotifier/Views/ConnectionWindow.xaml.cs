using System;
using System.Globalization;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media.Animation;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>Address + key, a Test that must pass before Save, and the explicit "trust this certificate" step.</summary>
public partial class ConnectionWindow : Window
{
    private sealed record Tested(ServerAddress Address, NotifierKey? NewKey, CertificatePin? Pin, string House);

    private readonly AppController _app;
    private CancellationTokenSource? _cts;
    private Tested? _tested;
    private CertificatePin? _candidatePin;
    private (ServerAddress Address, CertificateDetails Cert)? _offered;
    private bool _removeArmed;
    private bool _loading = true;

    internal ConnectionWindow(AppController app)
    {
        InitializeComponent();
        Ui.ApplyIcon(this);
        _app = app;
        Mark.Data = Ui.Geometry(Icons.Radar);
        SourceInitialized += (_, _) => Native.DarkTitleBar(this);
        Closed += (_, _) =>
        {
            _cts?.Cancel();
            KeyBox.Clear();
        };

        AddressBox.Text = _app.Settings.ServerUrl ?? "";
        _candidatePin = _app.Settings.GetPin();
        RemoveButton.Visibility = _app.Settings.HasConnection ? Visibility.Visible : Visibility.Collapsed;
        UpdateKeyHint();
        _loading = false;
        Loaded += (_, _) =>
        {
            if (AddressBox.Text.Length == 0) AddressBox.Focus();
            else KeyBox.Focus();
        };
    }

    private void UpdateKeyHint()
    {
        string? hint = _app.Settings.KeyHint;
        KeyHint.Text = !string.IsNullOrEmpty(hint) && _app.Settings.ProtectedKey is not null
            ? "Saved key …" + hint + " – leave empty to keep it"
            : "zmn_…";
        KeyHint.Visibility = KeyIsEmpty() ? Visibility.Visible : Visibility.Collapsed;
    }

    private bool KeyIsEmpty()
    {
        using var secure = KeyBox.SecurePassword; // a length check that does not copy the key into a string
        return secure.Length == 0;
    }

    private void OnInputChanged(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        UpdateKeyHint();
        _tested = null;
        SaveButton.IsEnabled = false;
        SaveNote.Visibility = Visibility.Visible;
        // what the card says was about the old input
        Card.Visibility = Visibility.Collapsed;
        _offered = null;
    }

    private async void OnTest(object sender, RoutedEventArgs e) => await RunTest();

    private async Task RunTest()
    {
        _tested = null;
        SaveButton.IsEnabled = false;
        if (!ServerAddress.TryParse(AddressBox.Text, out var address, out var addressError))
        {
            ShowProblem("Check the address", addressError);
            return;
        }
        if (AddressBox.Text != address.Base) AddressBox.Text = address.Base; // show what will be used

        NotifierKey? newKey = null;
        NotifierKey? key;
        if (!KeyIsEmpty())
        {
            if (!NotifierKey.TryParse(KeyBox.Password, out newKey, out var keyError))
            {
                ShowProblem("Check the key", keyError);
                return;
            }
            key = newKey;
        }
        else
        {
            // the saved key goes only to the server it was saved for
            var saved = _app.Address;
            if (saved is null || !string.Equals(saved.Host, address.Host, StringComparison.OrdinalIgnoreCase) || saved.Port != address.Port)
            {
                ShowProblem("Enter the key", saved is null
                    ? "Paste the desktop-app key ZIGMon showed when it was made."
                    : "This is a different server, so paste its key again: a saved key is only ever sent to the server it was saved for.");
                return;
            }
            key = _app.SavedKey();
            if (key is null)
            {
                ShowProblem("Enter the key", "The saved key cannot be read on this Windows account. Paste it again.");
                return;
            }
        }

        CertificatePin? pin = _candidatePin is not null && _candidatePin.Scope == address.PinScope ? _candidatePin : null;

        _cts?.Cancel();
        var cts = new CancellationTokenSource();
        _cts = cts;
        Busy(true);
        try
        {
            using var client = ZigmonClient.Create(address, key, pin);
            var hello = await client.HelloAsync(cts.Token);
            if (cts.IsCancellationRequested) return;
            var verdict = client.LastCertificateVerdict;
            ShowSuccess(address, hello, client.LastCertificate, verdict);
            _tested = new Tested(address, newKey, verdict == CertificateVerdict.Pinned ? pin : null, hello.House);
            SaveButton.IsEnabled = true;
            SaveNote.Visibility = Visibility.Collapsed;
        }
        catch (ZigmonException ex) when (ex.Kind == ZigmonErrorKind.Certificate && ex.Certificate is not null)
        {
            ShowCertificate(address, ex);
        }
        catch (ZigmonException ex)
        {
            ShowProblem(ex.Kind switch
            {
                ZigmonErrorKind.Unauthorized => "The key was not accepted",
                ZigmonErrorKind.RateLimited => "Too many tries",
                ZigmonErrorKind.Network => "Cannot reach the server",
                ZigmonErrorKind.Redirect => "The address redirects elsewhere",
                ZigmonErrorKind.Protocol => "That is not a ZIGMon answer",
                ZigmonErrorKind.Certificate => "Certificate refused",
                _ => "ZIGMon said no",
            }, ex.Message);
        }
        catch (OperationCanceledException)
        {
            // the window was closed or the test started again
        }
        finally
        {
            if (ReferenceEquals(_cts, cts)) Busy(false);
        }
    }

    private void Busy(bool busy)
    {
        TestButton.IsEnabled = !busy;
        TestWords.Text = busy ? "Testing…" : "Test connection";
        TestSpin.BeginAnimation(System.Windows.Media.RotateTransform.AngleProperty, busy
            ? new DoubleAnimation(0, 360, TimeSpan.FromSeconds(1)) { RepeatBehavior = RepeatBehavior.Forever }
            : null);
    }

    // ---- the result card -----------------------------------------------------------------

    private void Badge(string colour, string glyph)
    {
        CardBadge.Background = Ui.Brush(colour, 0x1F);
        CardBadge.BorderBrush = Ui.Brush(colour, 0x59);
        CardGlyph.Foreground = Ui.Brush(colour);
        CardGlyph.Text = glyph;
        Card.Visibility = Visibility.Visible;
    }

    private void ShowProblem(string title, string words)
    {
        Badge(Palette.Crit, "");
        Card.BorderBrush = Ui.Brush(Palette.Crit, 0x59);
        CardTitle.Text = title;
        CardBody.Text = words;
        CardBody.Visibility = Visibility.Visible;
        Facts.Visibility = Visibility.Collapsed;
        CertPanel.Visibility = Visibility.Collapsed;
        _offered = null;
    }

    private void ShowSuccess(ServerAddress address, HelloInfo hello, CertificateDetails? cert, CertificateVerdict verdict)
    {
        Badge(Palette.Ok, "");
        Card.BorderBrush = Ui.Brush(Palette.Ok, 0x59);
        CardTitle.Text = "Connected" + (hello.House.Length > 0 ? " to " + hello.House : "");
        CardBody.Text = hello.Key.Devices == 1
            ? "This key may see 1 sensor."
            : "This key may see " + hello.Key.Devices.ToString(CultureInfo.CurrentCulture) + " sensors.";
        Facts.Visibility = Visibility.Visible;
        FactHouse.Text = hello.House.Length > 0 ? hello.House : "–";
        FactVersion.Text = hello.Version.Length > 0 ? hello.Version : "–";
        FactKey.Text = (hello.Key.Name.Length > 0 ? hello.Key.Name : "(unnamed)")
            + (hello.Key.Hint.Length > 0 ? "  ·  …" + hello.Key.Hint : "");
        FactTls.Text = !address.IsHttps
            ? "Plain http to this computer only"
            : verdict == CertificateVerdict.Pinned
                ? "Encrypted · the certificate you trusted"
                : "Encrypted · certificate trusted by Windows";
        FactTls.Foreground = address.IsHttps ? Ui.Brush(Palette.Text) : Ui.Brush(Palette.Warn);

        if (cert is not null)
        {
            CertPanel.Visibility = Visibility.Visible;
            FillCertificate(cert);
            CertAdvice.Visibility = Visibility.Collapsed;
            TrustButton.Visibility = Visibility.Collapsed;
        }
        else
        {
            CertPanel.Visibility = Visibility.Collapsed;
        }
        _offered = null;
    }

    private void ShowCertificate(ServerAddress address, ZigmonException ex)
    {
        var cert = ex.Certificate!;
        bool changed = _candidatePin is not null && _candidatePin.Scope == address.PinScope;
        Badge(Palette.Warn, "");
        Card.BorderBrush = Ui.Brush(Palette.Warn, 0x59);
        CardTitle.Text = changed ? "The certificate has changed" : "Windows does not trust this certificate";
        CardBody.Text = ex.Message;
        Facts.Visibility = Visibility.Collapsed;
        CertPanel.Visibility = Visibility.Visible;
        FillCertificate(cert);
        CertAdvice.Visibility = Visibility.Visible;
        CertAdvice.Text = "Trust it only if this fingerprint is the one of your own ZIGMon's certificate - check it on the server, "
            + "for example: openssl x509 -noout -fingerprint -sha256 -in cert.pem. "
            + "Once trusted, only this exact certificate is accepted for " + address.PinScope + ".";
        TrustButton.Visibility = Visibility.Visible;
        TrustWords.Text = changed ? "Trust the new certificate" : "Trust this certificate";
        _offered = (address, cert);
    }

    private void FillCertificate(CertificateDetails cert)
    {
        CertSubject.Text = cert.Subject.Length > 0 ? cert.Subject : "(no name)";
        if (cert.Issuer.Length > 0 && cert.Issuer != cert.Subject) CertSubject.Text += "\nissued by " + cert.Issuer;
        else if (cert.Issuer == cert.Subject) CertSubject.Text += "\nself-signed";
        CertValidity.Text = "Valid " + cert.NotBefore.ToLocalTime().ToString("d", CultureInfo.CurrentCulture)
            + " – " + cert.NotAfter.ToLocalTime().ToString("d", CultureInfo.CurrentCulture)
            + (cert.NotAfter < DateTimeOffset.UtcNow ? "  (expired)" : "");
        CertFingerprint.Text = cert.Fingerprint;
    }

    private async void OnTrust(object sender, RoutedEventArgs e)
    {
        if (_offered is not { } o) return;
        _candidatePin = new CertificatePin(o.Address.PinScope, o.Cert.Sha256, o.Cert.Subject, DateTimeOffset.UtcNow);
        _offered = null;
        await RunTest();
    }

    // ---- the end -------------------------------------------------------------------------

    private void OnSave(object sender, RoutedEventArgs e)
    {
        if (_tested is not { } t) return;
        _app.ApplyConnection(t.Address, t.NewKey, t.Pin, t.House);
        KeyBox.Clear();
        Close();
    }

    private void OnCancel(object sender, RoutedEventArgs e) => Close();

    private void OnRemove(object sender, RoutedEventArgs e)
    {
        if (!_removeArmed)
        {
            _removeArmed = true;
            RemoveWords.Text = "Click again to remove";
            return;
        }
        _app.RemoveConnection();
        _loading = true;
        AddressBox.Text = "";
        KeyBox.Clear();
        _loading = false;
        _candidatePin = null;
        _tested = null;
        SaveButton.IsEnabled = false;
        Card.Visibility = Visibility.Collapsed;
        RemoveButton.Visibility = Visibility.Collapsed;
        UpdateKeyHint();
    }
}
