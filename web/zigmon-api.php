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
    foreach ($extra as $one) {          // a one-tap link's own secret, and its code
        $headers[] = $one;
    }
    $body    = null;

    if ($payload !== null) {
        // the sign-in is the cookie's to carry (5.19), never anything the
        // page's script put in a body
        unset($payload['session']);
        $body = json_encode($payload, JSON_UNESCAPED_UNICODE);
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

/** Pass a daemon reply straight through to the browser. */
function zigmon_relay(string $path, string $method = 'GET', ?array $payload = null,
                      float $timeout = 10.0, array $extra = []): void
{
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');

    if ($method !== 'GET' && $path !== '/api/tap' && zigmon_token() === null) {
        http_response_code(503);
        echo json_encode(['ok' => false, 'error' =>
            'the API token is unreadable — is zigmon.service running, and is '
            . ZIGMON_TOKEN . ' readable by the web server?']);
        return;
    }

    [$status, $body] = zigmon_call($path, $method, $payload, $timeout, $extra);
    if ($status === 0) {
        http_response_code(503);
        echo json_encode(['ok' => false, 'error' =>
            'the monitoring daemon is not responding — is zigmon.service running?']);
        return;
    }
    http_response_code($status);
    echo zigmon_squeeze($body);
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
