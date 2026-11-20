<?php
/**
 * zigmon-api.php — the page's side of the daemon API.
 *
 * index.php collects nothing itself. The daemon does all the work and exposes
 * it on http://127.0.0.1:<port>; this file is the thin client that talks to it.
 * Read endpoints are open; the two that change something (opening the Zigbee
 * network, erasing history) send the token the daemon dropped in a file
 * readable only by root and the web server's group.
 *
 * The browser never sees the token, and the web user holds no broker
 * credentials — the daemon owns those and is the only thing that talks to MQTT.
 */
declare(strict_types=1);

const ZIGMON_HOST  = '127.0.0.1';
const ZIGMON_PORT  = 9849;
const ZIGMON_TOKEN = '/run/zigmon/api-token';

/**
 * The context a download is fetched from the daemon with. It said nothing of
 * who was asking, so the daemon saw 127.0.0.1 - the relay itself, which no
 * block applies to and nothing is counted against.
 */
function zigmon_download_context(int $timeout = 30, string $session = '')
{
    $who = preg_replace('/[^0-9a-fA-F:.]/', '', (string) ($_SERVER['REMOTE_ADDR'] ?? ''));
    $headers = ['X-Zigmon-Client: ' . $who];
    // the sign-in in a header on this side too: in the address it is in
    // whatever logs the daemon's own requests
    $session = preg_replace('/[^A-Za-z0-9_-]/', '', $session);
    if ($session !== '') {
        $headers[] = 'X-Zigmon-Session: ' . $session;
    }
    return stream_context_create(['http' => ['timeout' => $timeout, 'ignore_errors' => true,
                                             'header' => implode("\r\n", $headers)]]);
}

/** The sign-in a request carries (5.19): its cookie, which this file sets
 *  when somebody signs in and the page's script cannot read (HttpOnly). It
 *  is never taken from an address or from a header the page could set. */
const ZIGMON_COOKIE = 'zigmon_session';
function zigmon_session(): string
{
    $session = (string) ($_COOKIE[ZIGMON_COOKIE] ?? '');
    return preg_match('/^[A-Za-z0-9_-]{20,80}$/', $session) ? $session : '';
}

/** The sign-in of a download: the same cookie. */
function zigmon_download_session(): string
{
    return zigmon_session();
}

/** Whether the page was reached over HTTPS - directly, or (only then) as the
 *  server in front of it says. A cookie marked Secure on a page served over
 *  plain HTTP would never come back, and nobody could sign in. */
function zigmon_https(): bool
{
    if (!empty($_SERVER['HTTPS']) && strtolower((string) $_SERVER['HTTPS']) !== 'off') {
        return true;
    }
    // a server in front that ends TLS itself says so; somebody saying so
    // falsely over plain HTTP only keeps their own cookie from coming back
    if (strtolower((string) ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')) === 'https') {
        return true;
    }
    return (string) ($_SERVER['SERVER_PORT'] ?? '') === '443';
}

/** The cookie a sign-in is kept in: HttpOnly (no script reads it), SameSite
 *  Strict (no other site's page sends it), Secure over HTTPS, for the whole
 *  dashboard. $until 0 takes it away. */
function zigmon_set_session(string $token, int $until): void
{
    setcookie(ZIGMON_COOKIE, $token, [
        'expires'  => $until,
        'path'     => '/',
        'secure'   => zigmon_https(),
        'httponly' => true,
        'samesite' => 'Strict',
    ]);
    if ($until === 0 || $token === '') {
        unset($_COOKIE[ZIGMON_COOKIE]);
    } else {
        $_COOKIE[ZIGMON_COOKIE] = $token;
    }
}

/** The first $most LETTERS of a string, not its first $most bytes (5.43.3).
 *  A password is up to 200 characters to the daemon, and the sign-in cut it
 *  at 200 bytes: a long one with any letter outside ASCII in it was cut
 *  short and never right again, or cut in the middle of a letter. Bytes
 *  that are not UTF-8 at all are cut as bytes, as before. */
function zigmon_cut(string $text, int $most): string
{
    if (preg_match('/^.{0,' . $most . '}/su', $text, $m)) {
        return $m[0];
    }
    return substr($text, 0, $most);
}

/** Read the API token the daemon wrote for us, or null if we can't. */
function zigmon_token(): ?string
{
    if (!is_readable(ZIGMON_TOKEN)) {
        return null;
    }
    $token = trim((string) @file_get_contents(ZIGMON_TOKEN));
    return $token !== '' ? $token : null;
}

/**
 * Call the daemon. Returns [status, body-string]; status 0 means unreachable.
 * $payload, when given, is sent as a JSON body and turns this into a POST.
 */
function zigmon_call(string $path, string $method = 'GET', ?array $payload = null,
                     float $timeout = 10.0, array $extra = []): array
{
    $headers = ['Accept: application/json'];
    $headers[] = 'X-Zigmon-Client: ' . preg_replace('/[^0-9a-fA-F:.]/', '', (string) ($_SERVER['REMOTE_ADDR'] ?? ''));
    // What a server in front says the caller was. It is not proof of anything
    // - anyone may send the header - so it travels under its own name and is
    // shown as a claim, never as the address. When the home server is told to
    // trust the one in front (set_real_ip_from), REMOTE_ADDR is already the
    // right answer and this says the same thing.
    if (!empty($_SERVER['HTTP_X_FORWARDED_FOR'])) {
        // Filtered first and cut from the RIGHT. It was cut to 120 characters
        // from the left, before anything else - which threw away the end of
        // the header, the one address in it the server in front wrote, and
        // left whatever the caller had made up in front of it. A caller could
        // be anybody it liked, 127.0.0.1 included.
        $via = preg_replace('/[^0-9a-fA-F:., ]/', '', (string) $_SERVER['HTTP_X_FORWARDED_FOR']);
        if (strlen($via) > 120) {
            $via = substr($via, -120);
            $via = ltrim(substr($via, (int) strpos($via, ',')), ', ');   // no half an address
        }
        $headers[] = 'X-Zigmon-Via: ' . $via;
    }
    // The sign-in, from its cookie (5.19) - checked to be only what a token
    // is made of, like every other value that goes into a header here: the
    // headers are joined with CRLF, and a value carrying a carriage return
    // would start a line of its own. The page's script never sees it; an
    // address never carries it.
    $session = zigmon_session();
    if ($session !== '') {
        $headers[] = 'X-Zigmon-Session: ' . $session;
    }
    // what the browser calls itself, cut short, so a list of who is signed in
    // can tell a phone from a laptop
    $agent = preg_replace('/[^\x20-\x7e]/', '', substr((string) ($_SERVER['HTTP_USER_AGENT'] ?? ''), 0, 120));
    if ($agent !== '') {
        $headers[] = 'X-Zigmon-Agent: ' . $agent;
    }
    // the name the page was opened on, as the browser sent it (5.43): a
    // passkey is tied to that name (its RP ID), and the daemon cannot see it -
    // its own requests all come from here. Only what a host and a port are
    // made of, like every other value in a header line here.
    $place = preg_replace('/[^A-Za-z0-9.:\[\]-]/', '', substr((string) ($_SERVER['HTTP_HOST'] ?? ''), 0, 255));
    if ($place !== '') {
        $headers[] = 'X-Zigmon-Host: ' . $place;
    }
    foreach ($extra as $one) {          // a one-tap link's own secret, and its code
        $headers[] = $one;
    }
    $body    = null;

    if ($payload !== null) {
        // the sign-in is the cookie's to carry (5.19), never anything the
        // page's script put in a body
        unset($payload['session']);
        // a byte that is not UTF-8 is put in as U+FFFD (5.43.3): json_encode
        // gave false for it, strlen(false) under strict_types threw, and
        // the page got an empty 500 for a name or a password cut in the
        // middle of a letter, or for anything a client sent that was not UTF-8
        $body = (string) json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
        $headers[] = 'Content-Type: application/json';
        $headers[] = 'Content-Length: ' . strlen($body);
    }
    // A one-tap link carries its own authority in its header and asks for no
    // API token; everything else that changes something must have one.
    if ($method !== 'GET' && $path !== '/api/tap') {
        $token = zigmon_token();
        if ($token === null) {
            return [0, ''];
        }
        $headers[] = 'X-Zigmon-Token: ' . $token;
        if ($body === null) {
            $headers[] = 'Content-Length: 0';
        }
    }

    $context = stream_context_create(['http' => [
        'method'        => $method,
        'timeout'       => $timeout,
        'ignore_errors' => true,
        'header'        => implode("\r\n", $headers),
        'content'       => $body,
    ]]);

    $url = 'http://' . ZIGMON_HOST . ':' . ZIGMON_PORT . $path;
    $reply = @file_get_contents($url, false, $context);
    if ($reply === false) {
        return [0, ''];
    }

    $status = 0;
    foreach (($http_response_header ?? []) as $header) {
        if (preg_match('#^HTTP/\S+\s+(\d+)#', $header, $m)) {
            $status = (int) $m[1];
        }
    }
    return [$status, (string) $reply];
}

/** Call the daemon and return the decoded reply, or null. */
function zigmon_get(string $path, float $timeout = 10.0): ?array
{
    [$status, $body] = zigmon_call($path, 'GET', null, $timeout);
    if ($status !== 200) {
        return null;
    }
    $data = json_decode($body, true);
    return is_array($data) ? $data : null;
}

// ---- (5.54) an upgrade going on, read from the disk --------------------------
// Whoever runs an upgrade - root's helper (deploy/zigmon_upgrade.py) and
// install.sh --upgrade - writes how far it is to one small file beside these
// pages. It is read here straight from the disk, never through the daemon:
// the daemon is what restarts in the middle of it, and then nginx and PHP.
// A dot name, which nginx never serves (location ~ /\. { deny all; }); read
// from this one fixed place only; believed for display and nothing else.
// "running" is believed for 30 min after it was written (longer than
// install.sh may take), "done" and "failed" for 10 min. Anything else - no
// file, older, written in the future, a state that is none of the three, not
// JSON - is as if there were no file, and every page behaves as it always did.
const ZIGMON_UPGRADE_FILE = __DIR__ . '/.upgrade.json';
const ZIGMON_UPGRADE_RUNNING_S = 1800;
const ZIGMON_UPGRADE_ENDED_S = 600;

/** One line of text from the file: control and format characters out
 *  (a bidi override included), cut to $most letters. */
function zigmon_upgrade_text($value, int $most): string
{
    if (!is_string($value)) {
        return '';
    }
    $text = preg_replace('/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]+/u', ' ', $value);
    if (!is_string($text)) {                 // not UTF-8 after all
        return '';
    }
    return trim(zigmon_cut(trim($text), $most));
}

/** A version: digits and dots, or nothing. */
function zigmon_upgrade_version($value): string
{
    return is_string($value) && preg_match('/^[0-9]{1,6}(\.[0-9]{1,6}){1,3}$/', $value) ? $value : '';
}

/** The upgrade going on (or ended within 10 min), checked field by field;
 *  null when there is none. Read once per request. $now for the checks. */
function zigmon_upgrading(?int $now = null): ?array
{
    static $held = false;
    if ($now === null && $held !== false) {
        return $held;
    }
    $got = null;
    try {
        $got = zigmon_upgrade_read($now ?? time());
    } catch (\Throwable $e) {
        $got = null;
    }
    if ($now === null) {
        $held = $got;
    }
    return $got;
}

function zigmon_upgrade_read(int $now): ?array
{
    $path = ZIGMON_UPGRADE_FILE;
    clearstatcache(true, $path);
    if (!@is_file($path) || @is_link($path)) {
        return null;
    }
    $size = @filesize($path);
    if ($size === false || $size < 2 || $size > 8192) {
        return null;
    }
    $raw = @file_get_contents($path, false, null, 0, 8193);
    if (!is_string($raw) || $raw === '') {
        return null;
    }
    $in = json_decode($raw, true, 4, JSON_INVALID_UTF8_SUBSTITUTE);
    if (!is_array($in)) {
        return null;
    }
    $state = $in['state'] ?? '';
    if (!in_array($state, ['running', 'done', 'failed'], true)) {
        return null;
    }
    $at = $in['at'] ?? null;
    if (!is_int($at) && !is_float($at)) {
        return null;
    }
    $at = (int) $at;
    if ($at <= 0 || $at > $now + 5) {         // written in the future: not believed
        return null;
    }
    if ($now - $at > ($state === 'running' ? ZIGMON_UPGRADE_RUNNING_S : ZIGMON_UPGRADE_ENDED_S)) {
        return null;
    }
    $int = function ($v, int $most): int {
        return (is_int($v) && $v >= 0 && $v <= $most) ? $v : 0;
    };
    $parts = $int($in['parts'] ?? 0, 999);
    $part = $int($in['part'] ?? 0, 999);
    if ($parts > 0 && $part > $parts) {
        $part = $parts;
    }
    $started = $int($in['started'] ?? 0, PHP_INT_MAX);
    if ($started > $at || $started < $at - 86400) {
        $started = 0;
    }
    $id = is_string($in['id'] ?? null) ? substr((string) preg_replace('/[^A-Za-z0-9]/', '', $in['id']), 0, 64) : '';
    return [
        'state'     => $state,
        'id'        => $id,
        // the same upgrade to the page without the id itself: what it keeps
        // its "reloaded once" and "seen it fail" by
        'key'       => substr(hash('sha256', 'zigmon-upgrade|' . $id . '|' . $started), 0, 16),
        'version'   => zigmon_upgrade_version($in['version'] ?? ''),
        'from'      => zigmon_upgrade_version($in['from'] ?? ''),
        'by'        => zigmon_upgrade_text($in['by'] ?? '', 100),
        'part'      => $part,
        'parts'     => $parts,
        'words'     => zigmon_upgrade_text($in['words'] ?? '', 160),
        'started'   => $started,
        'at'        => $at,
        'said'      => zigmon_upgrade_text($in['said'] ?? '', 400),
        'downgrade' => ($in['downgrade'] ?? false) === true,
        'now'       => $now,
    ];
}

/** What of it a page is shown: who asked, why it failed and its id only to
 *  somebody signed in. */
function zigmon_upgrade_shown(?array $u, bool $signed_in): ?array
{
    if ($u === null) {
        return null;
    }
    if (!$signed_in) {
        unset($u['by'], $u['said'], $u['id']);
    }
    return $u;
}

/** Whether this request carries a sign-in the daemon takes - asked of the
 *  daemon (PHP cannot tell a good token from a made-up one); while the daemon
 *  does not answer, nobody is. Asked at most once per request. */
function zigmon_upgrade_signed_in(): bool
{
    static $known = null;
    if ($known !== null) {
        return $known;
    }
    $known = false;
    if (zigmon_session() === '') {
        return false;
    }
    [$st, $body] = zigmon_call('/api/auth/whoami', 'GET', null, 3.0);
    if ($st === 200) {
        $who = json_decode((string) $body, true);
        $known = is_array($who) && is_array($who['who'] ?? null);
    }
    return $known;
}

/** The answer to a call the daemon did not answer while an upgrade goes on:
 *  "being upgraded", which the page expects, not "not responding". */
function zigmon_upgrade_answer(string $path, array $u): void
{
    http_response_code(503);
    header('Retry-After: 2');
    $v = $u['version'] !== '' ? $u['version'] : 'a new version';
    $out = ['ok' => false, 'upgrading' => zigmon_upgrade_shown($u, false),
            'error' => 'zigmon is being ' . ($u['downgrade'] ? 'taken back to ' : 'upgraded to ') . $v
                       . ' - it answers again in a moment'];
    if ($path === '/api/healthz') {
        // otp's /healthz: 503 in maintenance - what watches this machine sees
        // maintenance, not a machine that is down
        $out['state'] = 'in maintenance';
        $out['why'] = 'being upgraded to ' . $v;
        $out['version'] = $u['from'];
    }
    echo json_encode($out, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
}

/** Pass a daemon reply straight through to the browser. */
function zigmon_relay(string $path, string $method = 'GET', ?array $payload = null,
                      float $timeout = 10.0, array $extra = []): void
{
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');

    if ($method !== 'GET' && $path !== '/api/tap' && zigmon_token() === null) {
        $upgrading = zigmon_upgrading();                       // (5.54) the token goes with the daemon
        if ($upgrading !== null && $upgrading['state'] === 'running') {
            zigmon_upgrade_answer($path, $upgrading);
            return;
        }
        http_response_code(503);
        echo json_encode(['ok' => false, 'error' =>
            'the API token is unreadable — is zigmon.service running, and is '
            . ZIGMON_TOKEN . ' readable by the web server?']);
        return;
    }

    [$status, $body] = zigmon_call($path, $method, $payload, $timeout, $extra);
    if ($status === 0) {
        $upgrading = zigmon_upgrading();                       // (5.54)
        // (5.56) /healthz says "in maintenance" only while one runs: an upgrade
        // that ended (done or failed) with zigmon not answering is a machine
        // that is down, and what watches it must not hold its alerts for it
        if ($upgrading !== null && ($path !== '/api/healthz' || $upgrading['state'] === 'running')) {
            zigmon_upgrade_answer($path, $upgrading);
            return;
        }
        http_response_code(503);
        echo json_encode(['ok' => false, 'error' =>
            'the monitoring daemon is not responding — is zigmon.service running?']);
        return;
    }
    if ($path === '/api/status' && $status === 200) {
        $body = zigmon_upgrade_merge($body);                   // (5.54)
    }
    http_response_code($status);
    echo zigmon_squeeze($body);
}

/** (5.54) The status with the upgrade in it as "upgrading", so the page shows
 *  it at once - before anything restarts. Put in front of what the daemon
 *  said, never decoded and encoded again: the status is a third of a megabyte
 *  and its {} must stay {}. Nothing going on: the body exactly as it came. */
function zigmon_upgrade_merge(string $body): string
{
    $u = zigmon_upgrading();
    if ($u === null) {
        return $body;
    }
    $trim = ltrim($body);
    if ($trim === '' || $trim[0] !== '{' || ltrim(substr($trim, 1)) === '' || ltrim(substr($trim, 1))[0] === '}') {
        return $body;
    }
    $shown = json_encode(zigmon_upgrade_shown($u, zigmon_upgrade_signed_in()),
                         JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
    if (!is_string($shown)) {
        return $body;
    }
    return '{"upgrading":' . $shown . ',' . substr($trim, 1);
}

/** (5.54) ?api=upgrade-state: answered without the daemon. What the pages on
 *  the disk are (they change in the middle of an upgrade: the page loads
 *  them again once it is over), and whether the daemon answers now. */
function zigmon_upgrade_state(): array
{
    [$st] = zigmon_call('/api/health', 'GET', null, 3.0);
    $api = $st === 200;
    $u = zigmon_upgrading();
    return ['ok' => true, 'upgrading' => zigmon_upgrade_shown($u, $api && zigmon_upgrade_signed_in()),
            'pages' => zigmon_pages_stamp(), 'api' => $api, 'now' => time()];
}

/** What the pages on the disk are: index.php's size and time, hashed. */
function zigmon_pages_stamp(): string
{
    $page = __DIR__ . '/index.php';
    clearstatcache(true, $page);
    $mtime = @filemtime($page);
    $size = @filesize($page);
    return substr(hash('sha256', 'pages|' . (int) $mtime . '|' . (int) $size), 0, 12);
}

/**
 * A large answer, compressed for a browser that says it takes gzip.
 *
 * The status the page fetches on every change is a third of a megabyte of
 * JSON and shrinks to a tenth of that; over a phone's connection that is the
 * difference between the page following the house and trailing it. Only
 * where nothing is compressing already (PHP's own output compression) and
 * only past a size where it pays - a small answer is sent as it is.
 */
function zigmon_squeeze(string $body): string
{
    $accepts = (string) ($_SERVER['HTTP_ACCEPT_ENCODING'] ?? '');
    if (strlen($body) < 2048 || !function_exists('gzencode') || headers_sent()
        || stripos($accepts, 'gzip') === false || ini_get('zlib.output_compression')) {
        return $body;
    }
    $packed = gzencode($body, 4);
    if ($packed === false) {
        return $body;
    }
    header('Content-Encoding: gzip');
    header('Vary: Accept-Encoding');
    header('Content-Length: ' . strlen($packed));
    return $packed;
}
