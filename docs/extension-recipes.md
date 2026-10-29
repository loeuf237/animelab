# Imported extension recipes

AnimeLab does not execute Aniyomi APKs. It reads DEX strings and source-method constants, then serializes the supported selectors, request paths and data operations as a `SourceRecipe`.

`recipe_runtime.py` interprets the recipe's `runtime` object. It has no package-name or domain dispatch. `recipe_plans.py` holds declarative compatibility plans added during compilation for sources whose JSON or AJAX logic is not recoverable from constants alone. These plans are a compatibility layer, not a claim of automatic Kotlin translation.

Supported data operations include:

- JSON list catalogues, field aliases, caching and expansion into seasons/languages;
- JSON search results;
- AJAX responses containing episode or server HTML;
- episodes stored as text pairs or literal JavaScript URL arrays;
- season-page traversal and player redirects;
- JSON player responses and stream manifests.

Network calls keep the shared transport's URL validation, cookies, proxy and challenge handling. JSON is parsed as data; downloaded JavaScript and Kotlin are never evaluated. Cached catalogues are scoped to each source instance, and only valid list responses enter the cache. Protection and network failures propagate instead of returning a successful empty catalogue.

HTML sources still use the common HTML interpreter. Adding an API source requires a supported declarative plan; complex custom code, encryption and arbitrary bytecode control flow are not supported automatically. A complete Aniyomi-compatible execution environment would require a separate JVM/Android integration project.

## French Anime identity correction

French Anime (`…fr.frenchanime`, `french-anime.com`) is distinct from FRAnime (`…fr.franime`) and Hanime (`…all.hanime` or `…en.hanime`). Source identity uses the final package component, never a substring such as `hanime` inside `frenchanime`.

The French Anime recipe uses the upstream DataLifeEngine card selector and its `div.eps` episode encoding. Existing recipes demonstrably contaminated with `api:hanime` are repaired on load. The previous recipe is retained in revision history, and unrelated custom source recipes are preserved. Restart the server to load repaired recipes; refresh the page to clear previously displayed filters.

The source-specific adapter implementation has been removed; JSON and AJAX support now uses the shared recipe interpreter.

## Extension management study

The [Aniyomi/Anikku study](studies/aniyomi-anikku/README.md) compares upstream repositories, APK trust and loading, updates, multiple sources, preferences and runtime contracts with AnimeLab. It includes reproducible local findings and an implementation plan. The proposed package managers and runtime backends are not yet implemented.
