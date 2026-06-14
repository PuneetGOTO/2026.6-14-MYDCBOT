# GJBot Architecture

This project now has a package entry point while preserving the historical
monolithic implementation.

## Runtime Boundary

- `python -m gjbot` is the package entry point.
- `gjbot.legacy_app` contains the historical monolithic implementation.
- `role_manager_bot.py` remains executable for backward compatibility and
  delegates to `gjbot.runtime`.
- `gjbot.runtime` owns process startup: Alipay callback server, Web panel
  thread, and Discord bot startup.
- `gjbot.legacy` is a lazy bridge to the existing monolithic module.

## Subsystem Adapters

- `gjbot.app_context.ApplicationContext` is the typed dependency boundary for
  extracted services.
- `gjbot.adapters.*` contains external-system adapter helpers.
- `gjbot.domain.*` contains domain boundaries for economy, tickets,
  moderation, AI, voice, music, and payments.
- `gjbot.subsystems.bot` exposes the Discord bot object and command tree.
- `gjbot.subsystems.web` exposes the Flask app, Socket.IO object, and Web
  server runner.
- `gjbot.subsystems.payments` exposes the Alipay client, callback server, and
  payment success handler.
- `alipay_callback_handler.py` remains as a compatibility launcher. It no
  longer owns a separate payment implementation.
- `gjbot.subsystems.alipay_callback_legacy` preserves the previous standalone
  callback code for reference during migration.
- `gjbot.subsystems.music_cog_impl` contains the Discord music Cog.
- `music_cog.py` remains as a compatibility extension module.
- `gjbot.subsystems.database_impl` contains the database implementation.
- `database.py` remains as a compatibility shim for existing imports.
- `gjbot.subsystems.storage` exposes the database API through a package path.

## Compatibility Rule

The current refactor does not remove commands, routes, templates, static
assets, database functions, or payment behavior. New code should be added under
`gjbot/` first, then legacy functions can be moved behind these adapters in
small verified steps.

## Verification

Run:

```bash
python -m gjbot --check
python scripts/smoke_check.py
python -m py_compile role_manager_bot.py database.py music_cog.py alipay_callback_handler.py
```

## Data Safety Interfaces

New code should prefer the transaction-safe database helpers:

- `database.db_apply_user_balance_delta(...)`
- `database.db_set_user_balance(...)`
- `database.db_decrement_shop_item_stock(...)`
- `database.db_update_recharge_request_status(...)`

The older functions are still present so existing bot commands and Web routes
continue to work during incremental migration.
