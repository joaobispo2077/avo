# [1.14.0](https://github.com/joaobispo2077/avo/compare/v1.13.1...v1.14.0) (2026-10-10)


### Bug Fixes

* **tools:** allow traceback propagation through ToolError ([3958019](https://github.com/joaobispo2077/avo/commit/3958019014caba2dda8f5ed4881e3f0f093e960e))
* **deps:** bump urllib3 to 2.8.0 ([52fd6d9](https://github.com/joaobispo2077/avo/commit/52fd6d94cd8397bedd19d7425a4b7e3302c1c7b4))
* **deps:** clear high npm advisories in braces, brace-expansion, and undici ([69862c4](https://github.com/joaobispo2077/avo/commit/69862c4b2e4969b8c4dc224751085ab3d3ba3ddc))
* **breath:** defer numpy imports off the pipeline CLI path ([022d425](https://github.com/joaobispo2077/avo/commit/022d4250e55c2c20ffb827969ed6bed0f9339e0b))
* **ci:** fail closed when the mutation sticky only has a cached score ([7cc3fac](https://github.com/joaobispo2077/avo/commit/7cc3fac9bc7e86e8bba0a5a8ae61e8da30cf2722))
* **audit:** make dependency evidence fail closed ([e239a27](https://github.com/joaobispo2077/avo/commit/e239a271ce27c6d01621e4a516d9b934f3a392db))
* **shorts:** match short 05 as a path segment ([423650a](https://github.com/joaobispo2077/avo/commit/423650a7f83603baae342840bb03ada1cb8f6a88))
* **audio:** pad ducked inputs and trim at the region end ([a804f93](https://github.com/joaobispo2077/avo/commit/a804f93ad814bb62756db9c7986299894adb1af0))
* **cleanup:** preserve reconstruction inputs and record actual deletions ([19f783b](https://github.com/joaobispo2077/avo/commit/19f783b1c52513d7f2e94dafe9b0532e3b257738))
* **quality:** report unavailable dependency measurements ([3ccc08c](https://github.com/joaobispo2077/avo/commit/3ccc08c7e1b745d6b5faa47155fef023717b15ea))
* **deps:** track the depth-limited braces sources ([45b0dd8](https://github.com/joaobispo2077/avo/commit/45b0dd81229cd852ccd9e2d0c9d70196df09d4d6))
* **timeline:** validate candidate ids and isolate fresh render evidence ([ea06da7](https://github.com/joaobispo2077/avo/commit/ea06da72aaf15e25eb5baf19cd72998e4d3bc140))
* **review:** verify native cut materialization lineage ([736476d](https://github.com/joaobispo2077/avo/commit/736476d891ffdc56452168265dfdba8f5f5c508c))


### Features

* **cli:** add declarative native review batches ([b1b584b](https://github.com/joaobispo2077/avo/commit/b1b584bb037b3490151cb01bba8dd163b876be5e))
* **review:** add native structured vision passes ([d3111d3](https://github.com/joaobispo2077/avo/commit/d3111d3f7cbcdc1ccc98821f16ded2dcfa22a307))
* **breath:** add opt-in dialogue breath control ([e98fa00](https://github.com/joaobispo2077/avo/commit/e98fa009235e289f1dde355bd6d80fc289f75ca4))
* **cutting:** analyze routed audio with offline character alignment ([b3e1304](https://github.com/joaobispo2077/avo/commit/b3e130407579f477cd0e9adcd650bdde6562009a))
* **proof:** bind cutting approvals to canonical proof dependencies ([ad8cfa4](https://github.com/joaobispo2077/avo/commit/ad8cfa4a96d4d2e659a6e2035eb736db206a6cbd))
* **cutting:** classify safe boundaries and inherited joins ([99e5f1b](https://github.com/joaobispo2077/avo/commit/99e5f1bdad380e33f45dc4b9960ba8f5cb20658e))
* **proof:** compile initial cuts from canonical cmap ([64e9dde](https://github.com/joaobispo2077/avo/commit/64e9ddead03438a73c10b9b5ce21ab43ab1a3305))
* **cutting:** define evidence contracts and immutable storage ([b4f1df7](https://github.com/joaobispo2077/avo/commit/b4f1df7eaf4a09511abdafa7b1b42897b099798c))
* **review:** enforce automated review before human approval ([53e70c5](https://github.com/joaobispo2077/avo/commit/53e70c5493ef8a116f614aa279b096b9ee0206fe))
* **proof:** execute source-only graphs with native ffmpeg ([dc3acb1](https://github.com/joaobispo2077/avo/commit/dc3acb15031a5f105bfc9bac009d738a9248cb45))
* **render:** honor requested nvenc encoder for 4k composites ([a317f0b](https://github.com/joaobispo2077/avo/commit/a317f0bf7b624618399eb78ba4ba87220ab29985))
* **cutting:** orchestrate bounded review and trim commands ([6709e23](https://github.com/joaobispo2077/avo/commit/6709e23decbbd0b8a1f9d44fae81b269f3c53882))
* **render:** preoffset late overlay inputs to bound 4k memory ([c4ba590](https://github.com/joaobispo2077/avo/commit/c4ba59032de301313674631c86eb000d983ac162))
* **retakes:** propose complete takes and separate editorial reductions ([a489889](https://github.com/joaobispo2077/avo/commit/a489889b3a7042c3fe6f859ccd15821ee6e773ea))
* **evaluation:** report cutting precision coverage and correction metrics ([2e8cf81](https://github.com/joaobispo2077/avo/commit/2e8cf81214024751bdc36abbea70ae034a77f6ae))
* **cutting:** resolve protected pacing profiles across scopes ([1b02455](https://github.com/joaobispo2077/avo/commit/1b024554462c19a7ef3d1a36451f89666877e69b))
* **render:** select timeline mode from the render contract ([7f7d5a6](https://github.com/joaobispo2077/avo/commit/7f7d5a6f46c0c619706cf07aabb9c7638ad9109c))
* **audio:** validate source-scoped dialogue noise policies ([84c62fb](https://github.com/joaobispo2077/avo/commit/84c62fbc6280beaf025bf885119efd74e395cecf))
* **preview:** verify cutting windows through native media rendering ([72d36c0](https://github.com/joaobispo2077/avo/commit/72d36c0457bf454e4297d3739297a52683fd98ca))

## [1.13.1](https://github.com/joaobispo2077/avo/compare/v1.13.0...v1.13.1) (2026-10-01)


### Bug Fixes

* **deps:** bump brace-expansion and undici for npm audit ([33bb853](https://github.com/joaobispo2077/avo/commit/33bb85359334611aa70ec458209e47e205cac85c))
* **deps:** bump urllib3 to >=2.8.0 for pip-audit ([7ff1089](https://github.com/joaobispo2077/avo/commit/7ff10893c5f027b4809d3d1a77dde3c91d3dc928))

# [1.13.0](https://github.com/joaobispo2077/avo/compare/v1.12.0...v1.13.0) (2026-09-28)


### Features

* **candidate:** bind candidate snapshots and reconstruction ([964e4f9](https://github.com/joaobispo2077/avo/commit/964e4f9b54b3ab54b9318156ca29a43776a89f84))
* **watch:** budget long-form vision review ([6ede2d5](https://github.com/joaobispo2077/avo/commit/6ede2d5c6c6a2a9befb9be96ef38cc6814b75400))
* **audio:** compile continuous audio and timed events ([95cf048](https://github.com/joaobispo2077/avo/commit/95cf0483df25007d0d5da4502e7e4eddd3583d81))
* **proof:** compile proof plans and block forbidden ancestry ([992d753](https://github.com/joaobispo2077/avo/commit/992d753ef6d2e874d5c6a4b8bfcf70d922aac47f))
* **learndown:** export sanitized timeline learning ([f998c01](https://github.com/joaobispo2077/avo/commit/f998c011ccb2639b77243a7eeab8b07067abe2a6))
* **stills:** extract exact frames with admission checks ([f3c11f2](https://github.com/joaobispo2077/avo/commit/f3c11f2c156f414b284f87e2ede0009286b1ff02))
* **iterations:** persist cumulative iteration ledgers ([0bc29cc](https://github.com/joaobispo2077/avo/commit/0bc29ccfa89419c7838bca2ab298bbda041fafaf))
* **animation:** publish and reuse provider components ([56eac00](https://github.com/joaobispo2077/avo/commit/56eac007f55aeef2aa9689936db863a0dc3b8923))
* **models:** register vision model capability pins ([ac14820](https://github.com/joaobispo2077/avo/commit/ac148206e90d9cb687b7aad9b29ec6705401adc7))
* **render:** render portrait segments and verify movement ([1886cc7](https://github.com/joaobispo2077/avo/commit/1886cc7183509b7a11538313dd0178f1a88b4de3))
* **lineage:** trace audiovisual picture lineage ([193a5de](https://github.com/joaobispo2077/avo/commit/193a5deb0d7c7a298abc35e981d0cc66e1dddac6))

# [1.12.0](https://github.com/joaobispo2077/avo/compare/v1.11.3...v1.12.0) (2026-09-27)


### Bug Fixes

* **watch:** coerce prose and stamp requested windows ([ecffca8](https://github.com/joaobispo2077/avo/commit/ecffca8a7b70a734d5fb4edc7363e3744d7d0906))
* **models:** keep stronger-scope source and runtime ([000a574](https://github.com/joaobispo2077/avo/commit/000a574ec53f173c4903acdab85b958e8e90bd6f))


### Features

* **transcribe:** honor project and CLI language ([aa1ac1d](https://github.com/joaobispo2077/avo/commit/aa1ac1da3e3e6193c6d9f9dd6e63e191746be55d))
* **beat-edit:** map a reference edit and label techniques ([e12c3a2](https://github.com/joaobispo2077/avo/commit/e12c3a2ca7cb96b77d4c293ecfc889aeed9613cc))
* **shorts:** scale overlays and allow fractional stars ([a99cac9](https://github.com/joaobispo2077/avo/commit/a99cac979cd29382e14ae18a43f3eb4a76307a40))

## [1.11.3](https://github.com/joaobispo2077/avo/compare/v1.11.2...v1.11.3) (2026-09-20)


### Bug Fixes

* **ci:** use draftRelease so GitHub zips can attach ([c00084b](https://github.com/joaobispo2077/avo/commit/c00084b67afc1de48c16ef159b2565fd7ac5de7c))

## [1.11.2](https://github.com/joaobispo2077/avo/compare/v1.11.1...v1.11.2) (2026-09-20)


### Bug Fixes

* **ci:** attach zips to a draft GitHub release before it is immutable ([7225df6](https://github.com/joaobispo2077/avo/commit/7225df62165831f6e6a073a28f79ce4920f5ae53))

## [1.11.1](https://github.com/joaobispo2077/avo/compare/v1.11.0...v1.11.1) (2026-09-20)


### Bug Fixes

* **ci:** attach engine zips after semantic-release dispatch ([09a6870](https://github.com/joaobispo2077/avo/commit/09a6870548213b6e1b708b62ebbcba56538b8745))

# [1.11.0](https://github.com/joaobispo2077/avo/compare/v1.10.0...v1.11.0) (2026-09-20)


### Bug Fixes

* **deps:** pin adm-zip 0.6.1 for GHSA-7q85-xj36-vmfc ([a41fbf2](https://github.com/joaobispo2077/avo/commit/a41fbf29f01c1bba6f4cfa5df37ba91322dbdb27))
* **engine:** skip mcp.cli during PyInstaller collect ([8b7bf3a](https://github.com/joaobispo2077/avo/commit/8b7bf3ad513508185b8ec53b962116359b0da57f))


### Features

* **engine:** add unified avo dispatcher ([c8d09a6](https://github.com/joaobispo2077/avo/commit/c8d09a6a0d6ca152f67747e65274875a0363428c))
* **install:** fetch matching engine zip into ~/.avo ([93d331e](https://github.com/joaobispo2077/avo/commit/93d331ec0b8cea4aad0933d439a628fd3d4ff10e))
* **engine:** install engine zip with SHA-256 check ([503cf8a](https://github.com/joaobispo2077/avo/commit/503cf8a1b44dca3361f1acd1b7ddd2433f258faf))
* **engine:** resolve bundled config when frozen ([7d722e4](https://github.com/joaobispo2077/avo/commit/7d722e4214326e459b7b3721e2e51255dc7c6a13))
* **engine:** resolve checkout vs binary vs override ([91b13dd](https://github.com/joaobispo2077/avo/commit/91b13dd71f635f0741d479151329f0c00db80ae3))
* **engine:** skip Whisper download under AVO_CI_TRANSCRIBE_STUB ([5fa0a7e](https://github.com/joaobispo2077/avo/commit/5fa0a7efc9f0c61b60dc9992f776af534cbbbe55))

# [1.10.0](https://github.com/joaobispo2077/avo/compare/v1.9.0...v1.10.0) (2026-09-18)


### Bug Fixes

* **deps:** bump sharp 0.35.4 and pin js-yaml 4.3.2 ([52dec18](https://github.com/joaobispo2077/avo/commit/52dec18f7aeb5749d43422a0e9f736bfd062e261))
* **ci:** drop model-source xenon debt and command count ([5ba4e38](https://github.com/joaobispo2077/avo/commit/5ba4e38f9a58f1bd1a9cea8e0c5db2186b30eb2c))
* **timeline:** fail closed on incomplete audio and skip-evidence approvals ([a2f1dd8](https://github.com/joaobispo2077/avo/commit/a2f1dd86c0197c13dd0e9ade11cff934413dd700))
* **mcp:** point the MCP extra at the checkout ([20df606](https://github.com/joaobispo2077/avo/commit/20df606a74cd473e44289be56a39d4d05cbe70e3))
* **review:** require truthful Watch coverage and transcript identity ([30bb555](https://github.com/joaobispo2077/avo/commit/30bb55579dbd041dab749512485e313c712d87ac))
* **models:** stop model_sources importing stats ([9654bce](https://github.com/joaobispo2077/avo/commit/9654bce40444930ddb8966675527ad06b23ec8fc))


### Features

* **models:** add /avo.models inspect command ([bcd5739](https://github.com/joaobispo2077/avo/commit/bcd5739ca01a9bfeea6bd2b0d56179a16aa80a39))
* **schema:** add shared modelPin contract ([5da79ea](https://github.com/joaobispo2077/avo/commit/5da79ea0a0986ebefbe0e6ff30050f4b96b82368))
* **models:** disclose sources and fail-closed adapter load ([23cbe73](https://github.com/joaobispo2077/avo/commit/23cbe738fe0f51a7bf5ddca3462ca27920c02584))
* **shorts:** make HyperFrames templates provider-neutral and seek-safe ([88aebcc](https://github.com/joaobispo2077/avo/commit/88aebcc0560c2f648825a4f7cb86c896d5bc499a))
* **models:** resolve catalog id, source, and preflight ([7eb4bb7](https://github.com/joaobispo2077/avo/commit/7eb4bb78e5a8bfa3074b0ff57e57b8f9c11c9de8))
* **shorts:** separate proof attempts from artifacts and bind media QC ([4a7d470](https://github.com/joaobispo2077/avo/commit/4a7d47041f2f62d1f00e907f995a78e2dcd37c6f))
* **shorts:** version 1.2 contracts and canonical-root planning ([fdca86b](https://github.com/joaobispo2077/avo/commit/fdca86bc17637e4f01a4e6f87bdf392c5ae45dcf))

# [1.9.0](https://github.com/joaobispo2077/avo/compare/v1.8.0...v1.9.0) (2026-09-04)


### Bug Fixes

* **shorts:** extract batch root resolver for complexity and formatting ([b0077ec](https://github.com/joaobispo2077/avo/commit/b0077ec000825b81a0b1ddf62626658b68effc92))
* **shorts:** format batch-root path split for ruff ([75f52aa](https://github.com/joaobispo2077/avo/commit/75f52aa1f9651241915a9c0a6596c00a41ebb6f1))
* **render:** harden grade signalstats scratch, bound loudnorm to shortest stream, honor camera gain keys ([1fb38ba](https://github.com/joaobispo2077/avo/commit/1fb38bac2cc119f7e06f492e22ae8712f4d97057))
* **shorts:** normalize Windows path separators in batch_dir overrides on POSIX ([5b6497f](https://github.com/joaobispo2077/avo/commit/5b6497f607bd5c3571a3af595fc026663b02d224))


### Features

* **delivery-fidelity:** add assembly materialization, picture lineage, and source-fidelity QC ([eefe6a7](https://github.com/joaobispo2077/avo/commit/eefe6a74fa216f120f0620163441c5380f394331))
* **step-status:** add guided workflow footer contract for all AVO commands ([4f9a1fa](https://github.com/joaobispo2077/avo/commit/4f9a1fa44114654621bbc6bb54969085f4271e8b))
* **settings:** add scoped setting resolution with provenance ([45fc6f7](https://github.com/joaobispo2077/avo/commit/45fc6f76e28bd5f6cdb7eac545acbf06e3558673))
* **watch:** add scoped Watch execution policy and refactor watch-skill ([d396073](https://github.com/joaobispo2077/avo/commit/d39607399d53c771a45a85c4abbcc331503205e6))
* **shorts:** add v1.1 batch paths, ordered lineage, and planning fixtures ([f84911f](https://github.com/joaobispo2077/avo/commit/f84911f0b5b299f741e8d0680bef618233de65c2))

# [1.8.0](https://github.com/joaobispo2077/avo/compare/v1.7.0...v1.8.0) (2026-08-20)


### Features

* **quality:** add complexity deadcode duplication architecture tree and audit gates ([68ea0fe](https://github.com/joaobispo2077/avo/commit/68ea0fe78894fceff132e94896557146ea5a06f9))
* **cli:** add editlog refresh ([d814fa2](https://github.com/joaobispo2077/avo/commit/d814fa2515b6d855a57da1cc3d12d253f75198cb))
* **ci:** add Maxframe-style quality PR summaries ([af19f5e](https://github.com/joaobispo2077/avo/commit/af19f5ec911924b538365c09612a904d7ad52989))
* **quality:** add mutmut floors and src/avo dep-graph generator ([5fcd86a](https://github.com/joaobispo2077/avo/commit/5fcd86a9c4f8dfa5e302f85962b3b07d89f8828a))
* **ci:** add quality-gate contracts to PR table ([951cc2b](https://github.com/joaobispo2077/avo/commit/951cc2b36f6bd962d20dbf4ec8a0a15d09752d09))
* **quality:** add Ruff ESLint Prettier coverage runners ([d7bb117](https://github.com/joaobispo2077/avo/commit/d7bb11705398592f605c61afd4d4e7c93985dedb))
* **learndown:** copy EDITLOG lock once on export ([a65d5aa](https://github.com/joaobispo2077/avo/commit/a65d5aab831ead628a6d0295c630b3ec2babaa13))
* **mcp:** describe compact cleanup tool responses ([262b58c](https://github.com/joaobispo2077/avo/commit/262b58cc1f5894819d8c453027e7f265089d9651))
* **cleanup:** emit compact cleanup JSON and promote legacy reconstruction ([90c7222](https://github.com/joaobispo2077/avo/commit/90c722258651af13800d05c653af1d4e00be5594))
* **mutation:** export mutmut CI stats after run ([f0d6ada](https://github.com/joaobispo2077/avo/commit/f0d6adab349490ef3af30efec0875d5fc8c4779c))
* **editlog:** project JSON into a hybrid EDITLOG.md ([6ba0c1e](https://github.com/joaobispo2077/avo/commit/6ba0c1e05ade6b8d3ffeae2ed88840ca09962784))
* **timeline:** refresh EDITLOG after canonical writes ([72bc00f](https://github.com/joaobispo2077/avo/commit/72bc00fe9c98ac1d722d5fa0a2913ada130c354c))
* **mcp:** register avo_editlog_refresh ([48a0b0f](https://github.com/joaobispo2077/avo/commit/48a0b0f8340df2041dea55104dc63b97b17b6ee6))
* **workspace:** resolve WSL /mnt rawDir paths on Windows ([14eeae5](https://github.com/joaobispo2077/avo/commit/14eeae57bf809b861b0bb212eeedb6a8deeeb543))
* **wrap:** sample cleanup files and reuse draft freed bytes ([b4069b6](https://github.com/joaobispo2077/avo/commit/b4069b619d59f96d22194302f311acd7f67d603b))
* **mutation:** skip Gate 1/2 tests in mutmut ([b8b6b9f](https://github.com/joaobispo2077/avo/commit/b8b6b9fb8182ee2adcc10c5aaf00f74e961dfa9c))
* **mutation:** skip gitignore tests in mutmut ([bc48369](https://github.com/joaobispo2077/avo/commit/bc483696121f1c28cce4e8f5b05a4d9eba950511))
* **mutation:** split light/full mutmut profiles ([03f0c32](https://github.com/joaobispo2077/avo/commit/03f0c32d362ed849f6af26f06f3445fe8d81e3d6))
* **ci:** summarize size signal without pack dump ([c332d35](https://github.com/joaobispo2077/avo/commit/c332d3564cfc01ea110844dae61c992e17a81c76))
* **ci:** title comment Software metrics with numbers ([f78a148](https://github.com/joaobispo2077/avo/commit/f78a1481d14ccb09c9d870fa97879495ca46e189))

# [1.7.0](https://github.com/joaobispo2077/avo/compare/v1.6.0...v1.7.0) (2026-08-16)


### Features

* **mcp:** add local avo.mcp stdio server and CLI bridge ([4db81ad](https://github.com/joaobispo2077/avo/commit/4db81ad2fd686531fc27f082710fb904b29ff073))

# [1.6.0](https://github.com/joaobispo2077/avo/compare/v1.5.0...v1.6.0) (2026-08-14)


### Features

* **models:** add optional Bonsai understand catalog options ([1e3dd36](https://github.com/joaobispo2077/avo/commit/1e3dd36d3da5fb2b2df03aa4d05ddd70699f14f8))
* **understand:** fail closed when Bonsai Watch runtime is missing ([9693789](https://github.com/joaobispo2077/avo/commit/96937891c4f759a9087f6630c34c767a03e558e8))
* **hardware:** note optional Bonsai understand without changing llm ([49e6a92](https://github.com/joaobispo2077/avo/commit/49e6a923d61e1f12b8c13fd41184d716a42bf782))

# [1.5.0](https://github.com/joaobispo2077/avo/compare/v1.4.0...v1.5.0) (2026-08-14)


### Bug Fixes

* **audio:** allow camera_source_keys for dialogue restoration ([2fb4f3c](https://github.com/joaobispo2077/avo/commit/2fb4f3cf5ca8dd92bb68c890889f5752fb2c3ec8))
* **loudness:** let EDL loudness override project and provider ([7b46924](https://github.com/joaobispo2077/avo/commit/7b46924ad24239490c4ce5fb5a8071f871f39f14))
* **test:** restore original pyproject version after sync-script test ([b17f24b](https://github.com/joaobispo2077/avo/commit/b17f24b51d9ccf91487f5b8a0168348a084f8ef6))


### Features

* **timeline:** add canonical artifact JSON schemas ([a996922](https://github.com/joaobispo2077/avo/commit/a996922c96e66075e5970f4bdf9617f86d29f18d))
* **timeline:** add canonical CMap BMap Sync Tracks Animation stores ([5890a31](https://github.com/joaobispo2077/avo/commit/5890a31f25ba66fab93799218303b21847ab255b))
* **adapters:** add media inventory sync render and track compilers ([1d72fbd](https://github.com/joaobispo2077/avo/commit/1d72fbdb3ff6dab6e80b6f49424c4a7a925beea4))
* **timeline:** add review QC and watch adapters ([839a3ff](https://github.com/joaobispo2077/avo/commit/839a3ff7e44e97ac95fa274a4dff950fbabf9ad8))
* **transcribe:** bind review evidence to transcript candidates ([67af916](https://github.com/joaobispo2077/avo/commit/67af9164d7a2ae460c588f181ed9f5de36e5d790))
* **cli:** expose timeline sync review migrate cleanup commands ([cac024d](https://github.com/joaobispo2077/avo/commit/cac024ddba1e67e419270cb9d0aa24bf4cbf6dca))
* **render:** honor dialogue channels and optional track layers ([5e7fda1](https://github.com/joaobispo2077/avo/commit/5e7fda1849b3e6958dfc2a58b7b8c28d3b15b340))
* **shorts:** require Watch hashes before shorts promotion ([59f62e7](https://github.com/joaobispo2077/avo/commit/59f62e77c0297a36d363f339aa9ce67dd51c47de))
* **timeline:** resolve canonical map paths from video context ([9b6bb21](https://github.com/joaobispo2077/avo/commit/9b6bb21934c4405f87b0de45fc9510ec52ead3e5))
* **transcript:** validate master transcript against the export ([dd0e0df](https://github.com/joaobispo2077/avo/commit/dd0e0df32f9b4b965b6e9b063f9610a15a0dcc57))

# [1.4.0](https://github.com/joaobispo2077/avo/compare/v1.3.0...v1.4.0) (2026-08-14)


### Features

* **shorts:** add batch workflow CLI ([fd44cc9](https://github.com/joaobispo2077/avo/commit/fd44cc9d4f714a85b96129e8a20cce68b5a29e54))
* **shorts:** add contracts and planning ([1965c5b](https://github.com/joaobispo2077/avo/commit/1965c5bd4518fff47883d2d4ffa2d62b6507bd8d))
* **shorts:** add HyperFrames renderer ([9398c66](https://github.com/joaobispo2077/avo/commit/9398c6634a6b6b02e58111ca2dc10b20bb4a8f22))
* **gate1:** add optional ai-memory and ai-jail health probes ([7e3d8c3](https://github.com/joaobispo2077/avo/commit/7e3d8c3895dadd811b3d6eb01bd7972d6dec05ca))
* **shorts:** add QC and delivery ([3cfd216](https://github.com/joaobispo2077/avo/commit/3cfd216370a3cc8b34b88560bb3a919a870ecd9d))
* **setup:** harden ai-jail install verification per OS ([da2d74c](https://github.com/joaobispo2077/avo/commit/da2d74cc20be9173e6d18520502e26824318b5ad))
* **shorts:** prepare deterministic media ([20c5232](https://github.com/joaobispo2077/avo/commit/20c5232060feb1aef17c99b6699a816867b4c8a6))

# [1.3.0](https://github.com/joaobispo2077/avo/compare/v1.2.0...v1.3.0) (2026-08-03)


### Bug Fixes

* **test:** make limiter and video registry tests CI-portable ([f31bc1c](https://github.com/joaobispo2077/avo/commit/f31bc1c089a1b471323f33a9f120be716fd4cdd4))
* **test:** use loudness_profiles limiter in sfx pipeline test ([3ad56fe](https://github.com/joaobispo2077/avo/commit/3ad56fed5f985d8b555b72ecc5e2eb28ca9fe221))


### Features

* **providers:** add boil preset tokens to template ([50990fc](https://github.com/joaobispo2077/avo/commit/50990fcb92bca4b8853b538c5c4312aeb125e6d1))
* **audio:** add delivery loudness QC CLI ([7846054](https://github.com/joaobispo2077/avo/commit/784605416ee4964697213290a8021e7428a4fd95))
* **voiceover:** add external voiceover EDL helpers and preflight CLI ([1f40658](https://github.com/joaobispo2077/avo/commit/1f40658f591bf6660e28af2061e8dddf75f4c336))
* **schema:** add external voiceover fields to EDL schema ([62dcd49](https://github.com/joaobispo2077/avo/commit/62dcd49dce30afc420fcea00a953b09b6928f542))
* **edl:** add gain segment schema and validation ([31f2288](https://github.com/joaobispo2077/avo/commit/31f228823de592f237921379753fc6ea06e90f1a))
* **transcript:** add generate-from-master CLI for final artifacts ([f098207](https://github.com/joaobispo2077/avo/commit/f0982075227d90fe2bd3e7b1fa1d0dd6ea946b11))
* **exemplars:** add hyperframes-boil-insert bundle ([d1fccbb](https://github.com/joaobispo2077/avo/commit/d1fccbb2289893ce3d18dac30d72e03b4b13624e))
* **video-registry:** add in-repo registry stubs and bootstrap integration ([a824f7c](https://github.com/joaobispo2077/avo/commit/a824f7c335ccd6a01c7ba455ed05d0101c31bbbc))
* **commands:** add issues, supporters, and creators slash commands ([02ea447](https://github.com/joaobispo2077/avo/commit/02ea447255fdd4c491eb7500bf2cb599392f5d62))
* **provider:** add loudness and restoration defaults to provider schema ([436b557](https://github.com/joaobispo2077/avo/commit/436b557f86eddc18712e1965929d2d79edbb573f))
* **audio:** add noise analysis and suggestion CLI ([05decbd](https://github.com/joaobispo2077/avo/commit/05decbd76d33e81fc40c33bb61d024f6267db0cc))
* **video-work-modes:** add per-video state, context CLI, and model scoping ([199038a](https://github.com/joaobispo2077/avo/commit/199038a0010d89d2ba379a975b644e9d7d8749f8))
* **audio:** add percent-based restoration module ([4d1cadc](https://github.com/joaobispo2077/avo/commit/4d1cadcf119c7ed1e66795cace5fdfccf9cafb4e))
* **audio:** add platform loudness profile resolver ([b54cb15](https://github.com/joaobispo2077/avo/commit/b54cb151612067f01a783170cc677cd37f0faae7))
* **audio:** add read-only EQ suggestion heuristics ([d9b1fc5](https://github.com/joaobispo2077/avo/commit/d9b1fc5d5d11854e9a758d644492d183bbff381b))
* **audio:** add regional gain segments and suggestions ([6fc2bca](https://github.com/joaobispo2077/avo/commit/6fc2bcae728538be7d340498593df522bae45574))
* **providers:** add restoration_default_pct to template ([e5b1013](https://github.com/joaobispo2077/avo/commit/e5b1013b69a7f9484d23d1c7a92353a8687b071f))
* **github:** add structured issue form templates ([8a486f0](https://github.com/joaobispo2077/avo/commit/8a486f0f80555986bf3e2c95bb0c6c9bb4747ac1))
* **audio:** add unified read-only audio audit CLI ([53ced4b](https://github.com/joaobispo2077/avo/commit/53ced4b871b54c95dc2d54937dcc648bcce9e352))
* **commands:** add voiceover slash command and pipeline wiring ([959d0bb](https://github.com/joaobispo2077/avo/commit/959d0bbf3caa1a96ac71720c51aa9ef52be18a83))
* **schema:** declare audio loudness fields on project manifest ([812c87f](https://github.com/joaobispo2077/avo/commit/812c87f035794f64f9dca934fafb1f9acb8cf79b))
* **pipeline:** document percent-based noise reduction workflow ([e2e781b](https://github.com/joaobispo2077/avo/commit/e2e781b5d99e5a4e0cce4e3dbcd5d0924a3420c0))
* **audio:** extend analysis CLI for loudness, EQ, and gain ([2b6357b](https://github.com/joaobispo2077/avo/commit/2b6357b93bdc0dbb2f3f5e27ccc7054fef4560be))
* **render:** integrate loudness profiles, regional gain, and 4K transcript ([37920b0](https://github.com/joaobispo2077/avo/commit/37920b0024a99f84560318519667cab81ba2f499))
* **pipeline:** route wiggly boil inserts in motion skill ([1d5ea90](https://github.com/joaobispo2077/avo/commit/1d5ea90d87bf483bf24b89e366a2c857fc9cbd85))
* **render:** support external voiceover mux in render pipeline ([22ffd1c](https://github.com/joaobispo2077/avo/commit/22ffd1c2afa68360d7e9733cffd4e8cfe225e476))
* **edl:** validate restoration segment fields ([ae69b4e](https://github.com/joaobispo2077/avo/commit/ae69b4ed229cadf256df61ea9cd5a28f4a5caae7))
* **render:** wire restoration strength into segment extract ([3cee921](https://github.com/joaobispo2077/avo/commit/3cee921482ff2be3944c491c3d2cf7520ab46fab))

# [1.2.0](https://github.com/joaobispo2077/avo/compare/v1.1.1...v1.2.0) (2026-08-02)


### Features

* **scratch:** add learndown inventory scratch under .avo/tmp ([44c2cd8](https://github.com/joaobispo2077/avo/commit/44c2cd8ba2c1498ccab77f7e08c8c18ee0ef0a27))
* **learndown:** add provider export engine and backfill CLI ([d9743f3](https://github.com/joaobispo2077/avo/commit/d9743f343b85055d357cb3ff4af36677bfbf7f86))
* **learndown:** add provider export schemas and template layout ([26d0b72](https://github.com/joaobispo2077/avo/commit/26d0b72882e6bbcad15734aa0fe81933e202db6e))
* **inventory:** add scratch-out lifecycle and faster Windows cleanup ([81a68f7](https://github.com/joaobispo2077/avo/commit/81a68f73c6c0f53c8e0995f7a091b3484e763369))
* **update:** add self-update engine with provider preservation ([f400dc1](https://github.com/joaobispo2077/avo/commit/f400dc11530fb3dee843108f1d8ab2b31e764ec5))
* **edl:** add source-to-output timeline mapping CLI ([fb90ad2](https://github.com/joaobispo2077/avo/commit/fb90ad280d9300da141ce02cf3c40020d5c1f01b))
* **scripts:** add update native wrappers and npm run update ([ac9ee2e](https://github.com/joaobispo2077/avo/commit/ac9ee2e3e2f3079db724f79d54c594c92f677473))
* **wrap:** export provider learndowns and fix provider resolution ([010b4fc](https://github.com/joaobispo2077/avo/commit/010b4fce8d5144679a9193a2433e5ba6f50a799b))
* **validate:** gate /avo.update in Gate 2 usability checks ([9e2b8dd](https://github.com/joaobispo2077/avo/commit/9e2b8dd45c6c0eb21e0eab3eb8429158413311f9))
* **commands:** ship /avo.update slash command for end users ([454f163](https://github.com/joaobispo2077/avo/commit/454f163d2bbfdc44f62b0e2f620472ae84b8f89b))

## [1.1.1](https://github.com/joaobispo2077/avo/compare/v1.1.0...v1.1.1) (2026-08-02)


### Bug Fixes

* **release:** accept H1 linked changelog headings and drop develop alphas ([57bf96e](https://github.com/joaobispo2077/avo/commit/57bf96e206b5225b4087d37c8d2265b5ebd90b3f))

# [1.1.0](https://github.com/joaobispo2077/avo/compare/v1.0.1...v1.1.0) (2026-08-02)


### Bug Fixes

* **release:** accept semantic-release changelog headings in verify step ([1dd3201](https://github.com/joaobispo2077/avo/commit/1dd3201766cf222e9bf17fc539d831abd46d5005))
* **render:** apply yuva420p before overlay scale in composite graph ([80386c4](https://github.com/joaobispo2077/avo/commit/80386c456305a793c2208d3095becf90203c90c1))


### Features

* **docs:** add HyperFrames product-promo motion knowledge exemplars ([244fb37](https://github.com/joaobispo2077/avo/commit/244fb37ca9ae8ed68505a6b8d5562255254de1cb))
* **docs:** add HyperFrames short-form vertical motion knowledge exemplars ([c83a55a](https://github.com/joaobispo2077/avo/commit/c83a55a345c88403289e6e518e358abcb3558d30))
* **ci:** lint HyperFrames exemplar compositions in unit test job ([bd01cd5](https://github.com/joaobispo2077/avo/commit/bd01cd547867088818ce0bd379f9359831f18997))

## [1.0.1](https://github.com/joaobispo2077/avo/compare/v1.0.0...v1.0.1) (2026-08-02)
# 1.0.0-alpha.1 (2026-08-02)


### Bug Fixes

* **release:** accept semantic-release changelog headings in verify step ([c009702](https://github.com/joaobispo2077/avo/commit/c0097022ac240fb241545652048f439c7432c898))
* **release:** accept semantic-release changelog headings in verify step ([1dd3201](https://github.com/joaobispo2077/avo/commit/1dd3201766cf222e9bf17fc539d831abd46d5005))
* **validate-edl:** add tracked EDL JSON schema for CI validation ([7414515](https://github.com/joaobispo2077/avo/commit/7414515942423e3ca208a6b47ac912d5b647ddfd))
* **test:** add tracked locale stub for avo.locale stop gate ([ae5e75a](https://github.com/joaobispo2077/avo/commit/ae5e75a20560f0d49435c764568338577e7db9d3))
* **render:** apply yuva420p before overlay scale in composite graph ([80386c4](https://github.com/joaobispo2077/avo/commit/80386c456305a793c2208d3095becf90203c90c1))
* **release:** detect merge commits and use develop branch ([84b2392](https://github.com/joaobispo2077/avo/commit/84b23927d79f9185499dbd12da3e85ba09255e56))
* **install:** detect node on Linux via shell command -v ([c8ef247](https://github.com/joaobispo2077/avo/commit/c8ef2479228aad1117e6823aa97f922b90e76873))
* **release:** fix workflow_run branch detection and dedupe release triggers ([a837c16](https://github.com/joaobispo2077/avo/commit/a837c163353a5b501e0cb6fcacc54d167965585b))
* **release:** isolate concurrency by CI event to avoid cancel race ([663e698](https://github.com/joaobispo2077/avo/commit/663e698555fa51419c639d22cf39b60525553ae4))
* **release:** load pyproject sync as external semantic-release plugin ([c691588](https://github.com/joaobispo2077/avo/commit/c691588714f2bd02056399c23b68b27cd6fb9f1f))
* **release:** parse dry-run version and verify from package.json ([11b3478](https://github.com/joaobispo2077/avo/commit/11b3478d23dae616ae63e87e280adfb531e29140))
* **release:** parse first-release dry-run version case-insensitively ([2132aee](https://github.com/joaobispo2077/avo/commit/2132aee324f936876365a729e708dc052115d7b7))
* **render:** preserve orientation for portrait video sources ([#29](https://github.com/joaobispo2077/avo/issues/29)) ([1200463](https://github.com/joaobispo2077/avo/commit/1200463f00ae53fa562dc8ca2b5f8b7ec7d43f43))
* **release:** publish stable from release branch instead of main ([415aab1](https://github.com/joaobispo2077/avo/commit/415aab1962455f991f6b0dd6d04317029dcdf910))
* **subtitles:** raise MarginV to 90 to clear vertical safe zones ([#5](https://github.com/joaobispo2077/avo/issues/5)) ([87f00c6](https://github.com/joaobispo2077/avo/commit/87f00c6b9b4199dadf3c3b7a75bf818f3df0695e))
* **release:** resolve pyproject sync script from repo root ([33beb80](https://github.com/joaobispo2077/avo/commit/33beb8000ca2add5357c2fe15ce9033b093e994c))
* **render:** tone-map HLG/PQ sources to Rec.709 SDR ([#6](https://github.com/joaobispo2077/avo/issues/6)) ([60798b1](https://github.com/joaobispo2077/avo/commit/60798b1cd5cd4563875aeb06bb9252983084831a))
* **release:** treat matching pyproject version as sync success ([7607fe5](https://github.com/joaobispo2077/avo/commit/7607fe52a7b222bf5b7e1a4286a6758e6defbf93))
* **test:** use ASCII locale stub assertion to avoid encoding mismatch on CI ([5b597e8](https://github.com/joaobispo2077/avo/commit/5b597e839f3fca751093a581741ff56332bff757))
* **pack_transcripts:** write output as UTF-8 to avoid cp1252 encoding errors ([#10](https://github.com/joaobispo2077/avo/issues/10)) ([196d7e9](https://github.com/joaobispo2077/avo/commit/196d7e9377d7265ae61bd9e6189a4b12f33913c1))


### Features

* **commands:** add /avo.rights and /avo.audio-qc slash commands ([1728a4e](https://github.com/joaobispo2077/avo/commit/1728a4eaa47cd746be68938b0a244cc84fb8ff52))
* **commands:** add avo.captions and avo.deliver pipeline slices ([4ebea27](https://github.com/joaobispo2077/avo/commit/4ebea277118a90f56af0fc0b2040a308db9318bc))
* **commands:** add avo.shorts orchestrator and avo.reframe slice ([69a6b9e](https://github.com/joaobispo2077/avo/commit/69a6b9e9d9d7b479f710f688a2ecfe5fe6068490))
* **docs:** add HyperFrames product-promo motion knowledge exemplars ([244fb37](https://github.com/joaobispo2077/avo/commit/244fb37ca9ae8ed68505a6b8d5562255254de1cb))
* **docs:** add HyperFrames short-form vertical motion knowledge exemplars ([c83a55a](https://github.com/joaobispo2077/avo/commit/c83a55a345c88403289e6e518e358abcb3558d30))
* **commands:** add wave-2 AVO slash commands for upload prep, formats, and content routers ([a8448f3](https://github.com/joaobispo2077/avo/commit/a8448f3440de4cf6b78974d29fe902cc06b01c2a))
* **commands:** add wave-3 AVO slash commands ([5f1a8fe](https://github.com/joaobispo2077/avo/commit/5f1a8fe4cf01de6b5de8dc4c74c7e659c3e24c6b))
* **commands:** add wave-4 AVO slash commands ([2d4a4e3](https://github.com/joaobispo2077/avo/commit/2d4a4e38babcb8aadb249e44b8e4adfcc678f4aa))
* **ci:** lint HyperFrames exemplar compositions in unit test job ([bd01cd5](https://github.com/joaobispo2077/avo/commit/bd01cd547867088818ce0bd379f9359831f18997))

# 1.0.0 (2026-08-02)


### Bug Fixes

* **validate-edl:** add tracked EDL JSON schema for CI validation ([7414515](https://github.com/joaobispo2077/avo/commit/7414515942423e3ca208a6b47ac912d5b647ddfd))
* **test:** add tracked locale stub for avo.locale stop gate ([ae5e75a](https://github.com/joaobispo2077/avo/commit/ae5e75a20560f0d49435c764568338577e7db9d3))
* **release:** detect merge commits and use develop branch ([84b2392](https://github.com/joaobispo2077/avo/commit/84b23927d79f9185499dbd12da3e85ba09255e56))
* **install:** detect node on Linux via shell command -v ([c8ef247](https://github.com/joaobispo2077/avo/commit/c8ef2479228aad1117e6823aa97f922b90e76873))
* **release:** fix workflow_run branch detection and dedupe release triggers ([a837c16](https://github.com/joaobispo2077/avo/commit/a837c163353a5b501e0cb6fcacc54d167965585b))
* **release:** isolate concurrency by CI event to avoid cancel race ([663e698](https://github.com/joaobispo2077/avo/commit/663e698555fa51419c639d22cf39b60525553ae4))
* **release:** load pyproject sync as external semantic-release plugin ([c691588](https://github.com/joaobispo2077/avo/commit/c691588714f2bd02056399c23b68b27cd6fb9f1f))
* **release:** parse dry-run version and verify from package.json ([11b3478](https://github.com/joaobispo2077/avo/commit/11b3478d23dae616ae63e87e280adfb531e29140))
* **release:** parse first-release dry-run version case-insensitively ([2132aee](https://github.com/joaobispo2077/avo/commit/2132aee324f936876365a729e708dc052115d7b7))
* **render:** preserve orientation for portrait video sources ([#29](https://github.com/joaobispo2077/avo/issues/29)) ([1200463](https://github.com/joaobispo2077/avo/commit/1200463f00ae53fa562dc8ca2b5f8b7ec7d43f43))
* **release:** publish stable from release branch instead of main ([415aab1](https://github.com/joaobispo2077/avo/commit/415aab1962455f991f6b0dd6d04317029dcdf910))
* **subtitles:** raise MarginV to 90 to clear vertical safe zones ([#5](https://github.com/joaobispo2077/avo/issues/5)) ([87f00c6](https://github.com/joaobispo2077/avo/commit/87f00c6b9b4199dadf3c3b7a75bf818f3df0695e))
* **release:** resolve pyproject sync script from repo root ([33beb80](https://github.com/joaobispo2077/avo/commit/33beb8000ca2add5357c2fe15ce9033b093e994c))
* **render:** tone-map HLG/PQ sources to Rec.709 SDR ([#6](https://github.com/joaobispo2077/avo/issues/6)) ([60798b1](https://github.com/joaobispo2077/avo/commit/60798b1cd5cd4563875aeb06bb9252983084831a))
* **release:** treat matching pyproject version as sync success ([7607fe5](https://github.com/joaobispo2077/avo/commit/7607fe52a7b222bf5b7e1a4286a6758e6defbf93))
* **test:** use ASCII locale stub assertion to avoid encoding mismatch on CI ([5b597e8](https://github.com/joaobispo2077/avo/commit/5b597e839f3fca751093a581741ff56332bff757))
* **pack_transcripts:** write output as UTF-8 to avoid cp1252 encoding errors ([#10](https://github.com/joaobispo2077/avo/issues/10)) ([196d7e9](https://github.com/joaobispo2077/avo/commit/196d7e9377d7265ae61bd9e6189a4b12f33913c1))


### Features

* **commands:** add /avo.rights and /avo.audio-qc slash commands ([1728a4e](https://github.com/joaobispo2077/avo/commit/1728a4eaa47cd746be68938b0a244cc84fb8ff52))
* **commands:** add avo.captions and avo.deliver pipeline slices ([4ebea27](https://github.com/joaobispo2077/avo/commit/4ebea277118a90f56af0fc0b2040a308db9318bc))
* **commands:** add avo.shorts orchestrator and avo.reframe slice ([69a6b9e](https://github.com/joaobispo2077/avo/commit/69a6b9e9d9d7b479f710f688a2ecfe5fe6068490))
* **commands:** add wave-2 AVO slash commands for upload prep, formats, and content routers ([a8448f3](https://github.com/joaobispo2077/avo/commit/a8448f3440de4cf6b78974d29fe902cc06b01c2a))
* **commands:** add wave-3 AVO slash commands ([5f1a8fe](https://github.com/joaobispo2077/avo/commit/5f1a8fe4cf01de6b5de8dc4c74c7e659c3e24c6b))
* **commands:** add wave-4 AVO slash commands ([2d4a4e3](https://github.com/joaobispo2077/avo/commit/2d4a4e38babcb8aadb249e44b8e4adfcc678f4aa))

# Changelog

All notable changes to the **AVO orchestrator** (this repository) will be documented in
this file.

This project follows [Semantic Versioning](https://semver.org/) for software releases.

Format: `MAJOR.MINOR.PATCH` · Git tags: `vMAJOR.MINOR.PATCH` (annotated).

> **Note:** Video **export** versions for footage projects use a separate immutable scheme
> (`YYYYMMDD-video-slug-stage-v001`) documented in `AGENTS.md` and `docs/versioning.md`.
> Do not confuse editorial export versions with orchestrator SemVer.

## [Unreleased]

### Added

- Software engineering foundation: agent rules, SemVer/changelog policy, TDD rules,
  architecture and design-pattern skills ([software-foundation](./docs/software-foundation.md))
- CI/release verification via `tests.test_software_foundation`, gitignore and video-use trace tests
- Software quality refactor: pytest as canonical runner, full-suite CI parity,
  enhanced `release.yml` (version check + GitHub Release), [quality audit](./docs/software-quality-audit.md)
- Test layout: AVO core vs `tests/projects/` (footage-project specs excluded from CI via `pytest -m "not project"`)
