# Polymarket US credentials on this Mac

For Hyperliquid, see [HYPERLIQUID_SETUP.md](HYPERLIQUID_SETUP.md). Its API-wallet
setup is separate; do not put Hyperliquid keys in the Polymarket file below.

Store your Polymarket **US** Key ID and Secret Key in:

`/Users/daiyu/Library/Application Support/Kronos/polymarket-us.json`

```json
{
  "key_id": "",
  "secret_key": ""
}
```

Replace the empty strings locally with values from the Polymarket US developer
portal. Keep the file outside the repository. Its containing folder should have
permissions `700` and the file `600`. Never paste credentials into chat, report
files, notebooks, logs, or Git. This is a local plaintext file protected by file
permissions, not an encrypted vault.

`trading.credentials.load_polymarket_us_credentials()` reads that exact path and
returns the `key_id` and `secret_key` arguments for the Polymarket US SDK. It does
not print values, authenticate, or place orders. Empty values raise a generic
setup error. Preserve any existing credentials rather than replacing the file.

The project `.venv` contains the Polymarket US SDK, pinned in
`trading/requirements-us.txt`. Check saved credentials without submitting orders:

```sh
.venv/bin/python -m trading.check_polymarket_us
```

The check calls only `GET /v1/account/balances` and prints authentication status
and recognized balance fields. It never prints keys, headers, raw responses, or
exception messages. Success verifies this read endpoint, not order permissions.

The current `trading/polymarket.py` remains a public-data adapter for Polymarket
International and does not consume this file. The Polymarket US market adapter
and live execution runner still need to be wired separately.

For an international Polymarket account, use its wallet/signing authentication
instead; these US credentials are not interchangeable.
