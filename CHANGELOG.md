# [1.23.0](https://github.com/joaobispo2077/avo/compare/v1.22.0...v1.23.0) (2026-11-22)


### Bug Fixes

* **sound:** accept expected descendant staleness ([51362a7](https://github.com/joaobispo2077/avo/commit/51362a778b5598d04f9c3b2f784b687839b98426))
* **artcraft:** admit verified JSON-lines exports ([7e08650](https://github.com/joaobispo2077/avo/commit/7e08650c0beb17d19f5c80e81310ab8fdcbfd41c))
* **animation:** bind promotions to their provider ([2fe6fb7](https://github.com/joaobispo2077/avo/commit/2fe6fb7f5a0d1f7fb823d6e47061a213570bcf2a))
* **artcraft:** bind raw program canvas ([82ce908](https://github.com/joaobispo2077/avo/commit/82ce90826f53badf5f6f68ef97d6d3adf3cf66e7))
* **motion:** bind report freshness to context ([49c8174](https://github.com/joaobispo2077/avo/commit/49c81743f27ff5719bb5830ec5fb2505b92fae73))
* **proof:** bind sound admission to producer identity ([d19f994](https://github.com/joaobispo2077/avo/commit/d19f99447b10b724b90dd788b5d3448abe0e8d85))
* **camera:** clip precision layers to the canvas ([946a424](https://github.com/joaobispo2077/avo/commit/946a424cb39920a7ef45d1d4f711647e84dea4fe))
* **camera:** consume source orientation metadata ([8d8aa51](https://github.com/joaobispo2077/avo/commit/8d8aa5115269ef4adbf2f3f0f1b562e6f86a1e9f))
* **mcp:** declare ArtCraft tool group ([e400c4e](https://github.com/joaobispo2077/avo/commit/e400c4eb6c8d20fbca02b112bfd3e1cc5d65d939))
* **sound:** declare native source ancestry ([98de2d7](https://github.com/joaobispo2077/avo/commit/98de2d7cbc0a7826b5a95986ab7df3da12661ec6))
* **tracks:** enforce ArtCraft media scope ([334642d](https://github.com/joaobispo2077/avo/commit/334642d64dce5f94eb9597ded58c5672564c2d12))
* **camera:** fingerprint launched decoder bytes ([5a7d577](https://github.com/joaobispo2077/avo/commit/5a7d577ee64f183b607ac6b53c8fe90422768906))
* **proof:** fingerprint packaged native code ([d46f594](https://github.com/joaobispo2077/avo/commit/d46f59458cd49ff55ad068fbe7b371e2dd5a8353))
* **exports:** flag omitted editor fields ([6c304c8](https://github.com/joaobispo2077/avo/commit/6c304c8f71c9f9076d04b8440d3f070a4a9affee))
* **sound:** follow native audio boundary clocks ([6f6e1d6](https://github.com/joaobispo2077/avo/commit/6f6e1d6b67476217c84e0686c5bc71f91d976c99))
* **artcraft:** guard generated media admission ([38e09d5](https://github.com/joaobispo2077/avo/commit/38e09d54283590562f965712bd8e98f7e98c8fe9))
* **sound:** handle source inspection failures ([64f41c0](https://github.com/joaobispo2077/avo/commit/64f41c07365c1ee9339d7b2a4e3b488c62530d6c))
* **review:** hide observations on stale basis ([b57969f](https://github.com/joaobispo2077/avo/commit/b57969f1267726f94d3d2780db90154fdb433278))
* **motion:** isolate canonical head guards ([7c19892](https://github.com/joaobispo2077/avo/commit/7c19892d541075b4263783296de91242b28afecc))
* **motion:** keep applied plan review current ([9e9967c](https://github.com/joaobispo2077/avo/commit/9e9967c535284794d4cbe1ccd2a7f1ddb91791bc))
* **cleanup:** keep selected recovery results ([49a6d28](https://github.com/joaobispo2077/avo/commit/49a6d2868e308f3df2291d9e7ed3958dec572ce6))
* **artcraft:** locate installed AniCraft binaries ([78db4b5](https://github.com/joaobispo2077/avo/commit/78db4b54b7f8349fa14e41a96b482dfb31faf716))
* **ci:** normalize regional Ubuntu mirrors ([3e3e334](https://github.com/joaobispo2077/avo/commit/3e3e33415bdb43b128a1271e7850489779cf60b1))
* **proof:** preserve batch source verification ([5134ac4](https://github.com/joaobispo2077/avo/commit/5134ac4323b8274c562f16c0fb7aabfdd721249d))
* **sound:** preserve native programme clocks ([84f101e](https://github.com/joaobispo2077/avo/commit/84f101e0efa0bb4faafd943b447cde96500f8250))
* **camera:** preserve placed source input policy ([c64e6f7](https://github.com/joaobispo2077/avo/commit/c64e6f755242865ad7db572e2dec1e15dc40ad74))
* **exports:** preserve Resolve stereo routing ([1f21b38](https://github.com/joaobispo2077/avo/commit/1f21b3899cdb159ea65081e3156c5da5c859ec2e))
* **cleanup:** preserve shared ArtCraft packages ([67ad82b](https://github.com/joaobispo2077/avo/commit/67ad82bae06be5a4b549a15132ab5154a9dae8b3))
* **motion:** preserve unclaimed legacy metadata ([ade265f](https://github.com/joaobispo2077/avo/commit/ade265fe82c27eea02c9242efc254456d27ce634))
* **cleanup:** protect unsealed native versions ([5b5b7cb](https://github.com/joaobispo2077/avo/commit/5b5b7cb0750063259b9c2abe818d2c93bcae0cae))
* **exports:** read explicit gain filter ranges ([9b612f3](https://github.com/joaobispo2077/avo/commit/9b612f362f3bcdd62a4508f4eafa03d6c766d661))
* **review:** recheck safe-fix inputs ([5fd63fc](https://github.com/joaobispo2077/avo/commit/5fd63fcd7301c48e47aede56a7de975058ec6c0a))
* **cleanup:** recheck shared packages before deletion ([02dc189](https://github.com/joaobispo2077/avo/commit/02dc1895f90e374099aad0e1fe33b166dcfa91e7))
* **audio:** refresh cached marker disposition ([1a71ee5](https://github.com/joaobispo2077/avo/commit/1a71ee513bcfb156d603c7863372715fc90833a0))
* **camera:** reject mismatched crop geometry ([7a73f92](https://github.com/joaobispo2077/avo/commit/7a73f92f3f34c1632d157cb48949950849b9f960))
* **camera:** reject unqualified encoder depth ([7f9fa08](https://github.com/joaobispo2077/avo/commit/7f9fa084387c6f1c364b28a26b5b6982ada0eca4))
* **sfx:** report current heads and changed scope ([0f58da9](https://github.com/joaobispo2077/avo/commit/0f58da9f5171fee6b95212cd8ecf18d2b27a7bfc))
* **motion:** require current proof evidence ([742f736](https://github.com/joaobispo2077/avo/commit/742f736c6cc486bf6d2064778217bf961e87dbd2))
* **review:** require observed windows ([c5728b8](https://github.com/joaobispo2077/avo/commit/c5728b81b724b9a124cd1a970e32ee5cedb56857))
* **sound:** retain catalogue recovery state ([6502736](https://github.com/joaobispo2077/avo/commit/65027360557096a03bedfdfab0ae66b39e9d2632))
* **camera:** retain edge pixels on older runtimes ([f15057b](https://github.com/joaobispo2077/avo/commit/f15057b84162aedd016a02ad040cbdadf991d97b))
* **motion:** retain linked legacy cue direction ([6e08ffc](https://github.com/joaobispo2077/avo/commit/6e08ffc24e1ed0bfab680fc6a7d84af746e6f582))
* **reconstruction:** retain microproof gate metadata ([5caedd3](https://github.com/joaobispo2077/avo/commit/5caedd306b16abe24c5ca700d682a54ff77ea7cd))
* **camera:** retain native operation evidence ([a95f360](https://github.com/joaobispo2077/avo/commit/a95f360fb3ba715593f7c58afe8d4955a2d6cc46))
* **sfx:** retain owners for identical choices ([60110eb](https://github.com/joaobispo2077/avo/commit/60110eb2668ef57b8a21ced0fec66cd161bb7ff9))
* **craft:** retain pending request evidence ([d716729](https://github.com/joaobispo2077/avo/commit/d716729538ef8396701409c454a85010db4ada82))
* **camera:** retain precision through delivery ([1f91273](https://github.com/joaobispo2077/avo/commit/1f9127383241c7555d47a1d9a54f7a573f9a5321))
* **proof:** retain sound review receipts ([c7eb5a0](https://github.com/joaobispo2077/avo/commit/c7eb5a0acb1712dd49d31def5e3dbc920388b336))
* **sound:** retain staged selection dependencies ([1722bbd](https://github.com/joaobispo2077/avo/commit/1722bbd327854c186507a482d8569d952a335163))
* **preparation:** retain unchanged original text ([638ba2c](https://github.com/joaobispo2077/avo/commit/638ba2ce3f488e86dd6e478a4e91e685c0f26601))
* **motion:** retain unchanged visual direction ([b650a3d](https://github.com/joaobispo2077/avo/commit/b650a3d8d4974a0c071d1ad1c854b5b238350b3d))
* **sound:** retire removed visual events ([a968c4f](https://github.com/joaobispo2077/avo/commit/a968c4f9a76211ac2b681b55fc23a37fae97cd08))
* **render:** support longer numeric camera paths ([bb411ad](https://github.com/joaobispo2077/avo/commit/bb411ad208999fbaf7025f1bc6cdb50477c7f43a))
* **sound:** validate mix before apply ([efc5cac](https://github.com/joaobispo2077/avo/commit/efc5cace667d109a81c5b5c3e3c6ce9baad0ae4f))
* **artcraft:** verify retained tool fingerprints ([1b08b71](https://github.com/joaobispo2077/avo/commit/1b08b71b7127acd2a0144299e58539a0841c0212))
* **review:** verify saved preview window bytes ([e251c37](https://github.com/joaobispo2077/avo/commit/e251c37cd205ccfbf963adbcbf514c21c12d8580))
* **exports:** verify terminal trims against originals ([ac162c0](https://github.com/joaobispo2077/avo/commit/ac162c03a6421fb91f2fd42b626a2c2d69865bec))
* **sfx:** verify the measured mix input ([babee6a](https://github.com/joaobispo2077/avo/commit/babee6ae481753ac8f4f7f285e33b57a4d300550))


### Features

* **artcraft:** add fixed lower-third hold ([a94209a](https://github.com/joaobispo2077/avo/commit/a94209af0b2d77432ed3755484a137f232112b07))
* **camera:** add guarded canonical application ([c992821](https://github.com/joaobispo2077/avo/commit/c992821386785f91677bec7bff04dbd5429ec848))
* **sfx:** add local catalogue and search ([278fbe8](https://github.com/joaobispo2077/avo/commit/278fbe89b88e77fbfab9ec468cac76dee14fa0df))
* **artcraft:** add scoped authoring contracts ([2e28a0d](https://github.com/joaobispo2077/avo/commit/2e28a0d72b7f0de14775d1601d5a0e7cdc23d57b))
* **camera:** add sealed source-picture sampling ([6c9319e](https://github.com/joaobispo2077/avo/commit/6c9319e0da14c4275a40acd72fb76dba4834bf85))
* **camera:** add selected framing recipes ([9847e1d](https://github.com/joaobispo2077/avo/commit/9847e1dcab7d636fb1996d9baee145ff303d3df5))
* **sound:** add word-timed accents ([5916af5](https://github.com/joaobispo2077/avo/commit/5916af5a5746135d4abbdf6dbd8e3b1e1077f592))
* **proof:** admit linked emblem overlays ([51f76e3](https://github.com/joaobispo2077/avo/commit/51f76e30cb1874c0374ac92b92516bcc4856e7c7))
* **proof:** admit locked ArtCraft audio cues ([16b945f](https://github.com/joaobispo2077/avo/commit/16b945f325a53026b3878f84485a8a0f3403e2c9))
* **proof:** admit locked ArtCraft stills ([fc54cb3](https://github.com/joaobispo2077/avo/commit/fc54cb3080571c22488e7a527452b75fd4b367b9))
* **artcraft:** admit native overlays to proofs ([946d9cc](https://github.com/joaobispo2077/avo/commit/946d9ccbb9f87b72c0dae4f7ba41a8c6671b4fa6))
* **sfx:** anchor selected sounds to camera nodes ([366acd1](https://github.com/joaobispo2077/avo/commit/366acd1410f123fcca5785938d7cb72890e8c8e7))
* **anicraft:** animate retained vector artwork ([8c2cda3](https://github.com/joaobispo2077/avo/commit/8c2cda3fd5a5b047a194c9a2ab75e1e50c802c1d))
* **visual:** associate a selected face ([61afcb7](https://github.com/joaobispo2077/avo/commit/61afcb7e0ed019dce6639caf14273bb3c535b72a))
* **artcraft:** author AniCraft lower thirds ([61d4686](https://github.com/joaobispo2077/avo/commit/61d468657d9babd65284ff78a0553c23ed9111ec))
* **artcraft:** author DeckCraft slide fades ([2ef08da](https://github.com/joaobispo2077/avo/commit/2ef08daa0d4a3117b549691e4f7be012bc26346b))
* **artcraft:** author editable FigCraft variants ([1bb82c4](https://github.com/joaobispo2077/avo/commit/1bb82c406837b0b6065eee96d9db57e90b17b84b))
* **artcraft:** author editable PhotoCraft cards ([68ec8f4](https://github.com/joaobispo2077/avo/commit/68ec8f4d4562bf3c1cd8e1f69969571190a9fe1c))
* **artcraft:** author editable vector cards ([aaf5d1b](https://github.com/joaobispo2077/avo/commit/aaf5d1bd4ec4d7be5732992a2367ce1d564fa72d))
* **artcraft:** author FilmCraft interchange ([05853bf](https://github.com/joaobispo2077/avo/commit/05853bf3a604cf6a885d890bafa2684b24a01fcc))
* **artcraft:** author isolated SoundCraft cues ([2ec4361](https://github.com/joaobispo2077/avo/commit/2ec4361c169e2b836c55babc9b772ee0409c728a))
* **artcraft:** author portrait lower thirds ([90279a7](https://github.com/joaobispo2077/avo/commit/90279a77509579dd3ebe7415535a081d067a8fa0))
* **sound:** bind accents to source occurrences ([c92e228](https://github.com/joaobispo2077/avo/commit/c92e22805a07521183f992dce86d8fb9892fb7c4))
* **sound:** bind admitted source streams ([3b51f99](https://github.com/joaobispo2077/avo/commit/3b51f99d0e7e716b313e0fed32009e45db406b81))
* **motion:** bind camera recipes to concepts ([337fc43](https://github.com/joaobispo2077/avo/commit/337fc4306c5f722770c4dc8bedb9d3d30fe65b04))
* **artcraft:** bind exact emblem handoffs ([8e2cd14](https://github.com/joaobispo2077/avo/commit/8e2cd1481a2969a12ac6b99becd74ef614b01c1a))
* **camera:** bind rendering environment ([fd77024](https://github.com/joaobispo2077/avo/commit/fd77024d4b332913dc394ce8e7e8b71139c7835b))
* **assets:** bind reviewed asset choices ([723cf1c](https://github.com/joaobispo2077/avo/commit/723cf1c8d054b2a9fc338a20d46572e47e6b15fa))
* **artcraft:** bind reviewed label defaults ([654a0f7](https://github.com/joaobispo2077/avo/commit/654a0f75c7e27d28da1d8d3cf19537fafa90ee4e))
* **direction:** bind reviewed references ([e84c223](https://github.com/joaobispo2077/avo/commit/e84c223a5c101afc7f0a5c52febc7f65c67d8c14))
* **visual:** bind source face observations ([0f483d0](https://github.com/joaobispo2077/avo/commit/0f483d041ac0e4544ed2d418f14bf693955acc41))
* **preparation:** bind word timing evidence ([418638f](https://github.com/joaobispo2077/avo/commit/418638f70ff82f39b940203e2b6626c0be46a9b9))
* **review:** bind workaround evidence ([4762131](https://github.com/joaobispo2077/avo/commit/4762131d09e65c0434414ca42b2bff0e455e77bb))
* **mcp:** bridge scoped ArtCraft jobs ([736e10d](https://github.com/joaobispo2077/avo/commit/736e10dddb5dbad67625fce750a68733b3c2a74a))
* **artcraft:** cancel owned native renders ([2436623](https://github.com/joaobispo2077/avo/commit/24366231534bc147276da4e931af81cba6f72986))
* **assets:** compare local options ([1f07b1c](https://github.com/joaobispo2077/avo/commit/1f07b1c5f8e8f1e1485c1a8c2e4571616bb1a445))
* **sound:** compile published sound into proofs ([d6ba1a5](https://github.com/joaobispo2077/avo/commit/d6ba1a58f6a40066fad63f25a00bb4df906e812c))
* **sound:** compile selected sound into proofs ([cc5af1a](https://github.com/joaobispo2077/avo/commit/cc5af1a4159dc5d2083030931fb07cc3e3a7260d))
* **camera:** compile source-bound face framing ([bd9164a](https://github.com/joaobispo2077/avo/commit/bd9164ac6304ffd5f4f671d1b1d80148ea6165ea))
* **camera:** compile source-bound proof plans ([a0d47ef](https://github.com/joaobispo2077/avo/commit/a0d47ef2889e71a32b4bbc750c6b45116cedc05d))
* **artcraft:** declare native provider metadata ([0266386](https://github.com/joaobispo2077/avo/commit/026638674be95f99208e90905259ad839e5b123f))
* **visual:** decode and measure face proxies ([f1f43e7](https://github.com/joaobispo2077/avo/commit/f1f43e713a9aa1662c527ea5249e6a22c82da4a2))
* **craft:** define queue decision records ([e4877ff](https://github.com/joaobispo2077/avo/commit/e4877ffd3a940ff06c9c40eb858296f7feb4a5ae))
* **craft:** define selected production ownership ([7a70d52](https://github.com/joaobispo2077/avo/commit/7a70d520b682113236f9152fea966598af5f55a9))
* **artcraft:** edit labels in native copies ([0c5cb9e](https://github.com/joaobispo2077/avo/commit/0c5cb9e820effdadf358f81c13c63f4373a5f5bf))
* **sound:** enforce section ownership ([784b3e3](https://github.com/joaobispo2077/avo/commit/784b3e3d491c14936701d5c051ecbe54a532bf72))
* **vectorcraft:** export editable emblems ([0a8713c](https://github.com/joaobispo2077/avo/commit/0a8713cc381d6b5e79d2a5e44e0db38af71669f5))
* **learndown:** export scoped timeline learning ([c8e10a9](https://github.com/joaobispo2077/avo/commit/c8e10a9811a0c1270232a83f9858edbb2d36a63d))
* **exports:** export validated centered zoom ([83ee084](https://github.com/joaobispo2077/avo/commit/83ee084974e8ba213249aac1a5f128e76623a701))
* **mcp:** expose editor review commands ([6f43c9d](https://github.com/joaobispo2077/avo/commit/6f43c9dc348ef440f205ca9ec81c84d76fdac093))
* **mcp:** expose editor target qualification ([c67a1bc](https://github.com/joaobispo2077/avo/commit/c67a1bcaf9af7d97c3634dc8c869eab75d8a0e46))
* **mcp:** expose editor trim routing ([9b6863c](https://github.com/joaobispo2077/avo/commit/9b6863cd0112387b1132f0fb903784a5d7a61b33))
* **preparation:** expose evidence choices ([b269232](https://github.com/joaobispo2077/avo/commit/b2692328fa3d6182cbef90e3e4786baca04374f4))
* **sound:** expose guarded sound application ([459a204](https://github.com/joaobispo2077/avo/commit/459a204bdb8dd016d09be0fab0742b2b57104b3f))
* **sound:** expose proposal command ([c7f7c28](https://github.com/joaobispo2077/avo/commit/c7f7c28a6c67d101d335a6f2b5be98580a4d4a7e))
* **sfx:** expose provider favorite commands ([e44396b](https://github.com/joaobispo2077/avo/commit/e44396b8ed79c4391e8323b7ee44a5deefee8940))
* **artcraft:** expose read-only routing commands ([8b1e7af](https://github.com/joaobispo2077/avo/commit/8b1e7af463a900bba85e483c45560e892be094ff))
* **preparation:** expose recovery commands ([cd62b46](https://github.com/joaobispo2077/avo/commit/cd62b46f1150b32aa3be5d54c51efec68cdf4d78))
* **motion:** expose reference analysis ([3e4874f](https://github.com/joaobispo2077/avo/commit/3e4874f5d8bf5c658af694de61146bbfe11467eb))
* **motion:** expose reference decisions ([e207e1b](https://github.com/joaobispo2077/avo/commit/e207e1bdfb1572f5779ece58daddfa876cf8e32c))
* **cli:** expose scoped ArtCraft recovery ([1ddc6d8](https://github.com/joaobispo2077/avo/commit/1ddc6d81b6b07eb62781eb58914d8c6963241d02))
* **cli:** expose scoped motion plans ([ea62c04](https://github.com/joaobispo2077/avo/commit/ea62c04bf6dfca45ced6df8bc4556f3c1d65c6c6))
* **camera:** expose selected authoring commands ([705f1bf](https://github.com/joaobispo2077/avo/commit/705f1bfa4ae3721829d8d6e440a05483c88742fd))
* **motion:** expose selected face analysis ([6726af9](https://github.com/joaobispo2077/avo/commit/6726af94a1789146269cfa938dedaf3095378cc9))
* **pipeline:** expose work decision command ([6e6ef3b](https://github.com/joaobispo2077/avo/commit/6e6ef3bea4dc85fdf148e73c3d757d686ded3efa))
* **sound:** fence selected track readers ([77e2b6c](https://github.com/joaobispo2077/avo/commit/77e2b6c7eb3b4d3139ed10eb52e52b9b93d9e8fd))
* **sound:** fit source-bound sound candidates ([e52bbf6](https://github.com/joaobispo2077/avo/commit/e52bbf612c866feb7b609efa33d0d01ad18cf939))
* **artcraft:** freeze native export evidence ([525538c](https://github.com/joaobispo2077/avo/commit/525538c5984efe2ef810348a7b8fbe15085de103))
* **sound:** freeze per-event sound choices ([a9dd3e8](https://github.com/joaobispo2077/avo/commit/a9dd3e8883d4a09add7c5e98f1458e7512a10059))
* **visual:** freeze selected face measurements ([2ed5779](https://github.com/joaobispo2077/avo/commit/2ed5779817ff7cba6997b4c6014185ddd7b52692))
* **visual:** freeze selected reference evidence ([715b3b6](https://github.com/joaobispo2077/avo/commit/715b3b6f02850df2f3607ab19ed435e801d30fc3))
* **camera:** guard advanced strategy readers ([ae613e4](https://github.com/joaobispo2077/avo/commit/ae613e4c1340831f08824327538e99d177f5eeb3))
* **sound:** honor scoped repetition window ([ca69c49](https://github.com/joaobispo2077/avo/commit/ca69c49b4062257b66abfc09b11d80e4125208bd))
* **exports:** include Resolve validation gain ([b5b384f](https://github.com/joaobispo2077/avo/commit/b5b384f55d1008dcdd8c7a56674ec3ad8932ec7d))
* **exports:** inspect constant returned gain ([97dd802](https://github.com/joaobispo2077/avo/commit/97dd802f9a45446ef96ebdd610d7e9dd4aebcb65))
* **artcraft:** inspect interrupted jobs ([b85846c](https://github.com/joaobispo2077/avo/commit/b85846cebc920970a30192ff98c4898ae14cf277))
* **preparation:** inspect literal notes ([5a38ef2](https://github.com/joaobispo2077/avo/commit/5a38ef2b1d613cf505469544da1310ba933164c0))
* **artcraft:** inspect retained native jobs ([5cbd47d](https://github.com/joaobispo2077/avo/commit/5cbd47d5216fc860ad2c5b0a348a23300ee2a540))
* **exports:** inspect returned static zoom ([d1d41b1](https://github.com/joaobispo2077/avo/commit/d1d41b181faed604f3ba2dd2ffb824ec8413552e))
* **preparation:** inspect source speech coverage ([c7e2d1a](https://github.com/joaobispo2077/avo/commit/c7e2d1a13a1964f97d9d22befa395f823f3386a6))
* **artcraft:** inventory native reconstruction inputs ([5bd082a](https://github.com/joaobispo2077/avo/commit/5bd082a8ae1f361dbfbc4623f8c73a843ae094c7))
* **preparation:** journal evidence choices ([a5ab429](https://github.com/joaobispo2077/avo/commit/a5ab429b7e62575a3ef41e96ff71214c2330fe5f))
* **preparation:** journal recovery attempts ([e21eac5](https://github.com/joaobispo2077/avo/commit/e21eac5693030e21ffeeea76019326ecb9752c30))
* **exports:** link admitted alpha in handoffs ([a086e67](https://github.com/joaobispo2077/avo/commit/a086e6710cf4e0f08a3111919cc732dfb3b15ac1))
* **review:** link craft cues to encoded frames ([63d0682](https://github.com/joaobispo2077/avo/commit/63d0682f79da9e61e5e9525a7c2c3b787b3a532a))
* **artcraft:** link proof review evidence ([75e8146](https://github.com/joaobispo2077/avo/commit/75e81462b9d949cf21181e74e26060409f3572e8))
* **motion:** link sound choices in review ([8ef15cb](https://github.com/joaobispo2077/avo/commit/8ef15cb20be541875ce76bc2ace8be42f27bbdbb))
* **motion:** link storyboard to reviewed cues ([6bec41f](https://github.com/joaobispo2077/avo/commit/6bec41f8f0f0f91cba01ceba374441fb7603132c))
* **sfx:** measure native source descriptors ([7c20101](https://github.com/joaobispo2077/avo/commit/7c201011f3bc4f35a9ee51ce7cf2193fd1ac5e53))
* **visual:** measure reference frame motion ([d2d8dd4](https://github.com/joaobispo2077/avo/commit/d2d8dd49f2aef97fe68362fd128dc9b40835ab7d))
* **visual:** measure reference timing ([b95cbff](https://github.com/joaobispo2077/avo/commit/b95cbff88369b424ac0f04f896ceb652319644f6))
* **sound:** measure selected dialogue margin ([b3b4eff](https://github.com/joaobispo2077/avo/commit/b3b4eff58001ca3d54fddc9885a3b301d3bc93e6))
* **artcraft:** pack verified alpha video ([455d628](https://github.com/joaobispo2077/avo/commit/455d628883443535bc21ee576af6b651b4a04051))
* **sound:** persist bounded event proposals ([5195688](https://github.com/joaobispo2077/avo/commit/51956880af33d9b36c19d4bb411c174306597dde))
* **craft:** persist requested work references ([aecb6bd](https://github.com/joaobispo2077/avo/commit/aecb6bdad2cf5b520fbb4392ba29fc05484a2fa1))
* **artcraft:** pin native kits per video ([74fc603](https://github.com/joaobispo2077/avo/commit/74fc603e8cf546b96f3b515b292e292a901240a2))
* **models:** preflight local YuNet ([75fe34f](https://github.com/joaobispo2077/avo/commit/75fe34feee247a0313f57cbc83d7e43d0f7e01c8))
* **exports:** prepare and compare editor XML ([01eab0e](https://github.com/joaobispo2077/avo/commit/01eab0e8b96ee91db91c9d7228cd3953ed6e6bb7))
* **timeline:** prepare guarded owner revisions ([6685c0a](https://github.com/joaobispo2077/avo/commit/6685c0a51670c8eb0aca3e757bb04d33c1edbc87))
* **artcraft:** prepare scoped native jobs ([2ab5eda](https://github.com/joaobispo2077/avo/commit/2ab5eda2aa487967310015db48995e242b22d83b))
* **proof:** preserve precision across layers ([4414253](https://github.com/joaobispo2077/avo/commit/44142535f994a705a9e9fcc735c2032df671e4af))
* **exports:** preserve timeline display origin ([c7ee32e](https://github.com/joaobispo2077/avo/commit/c7ee32e6fc4b458d37daff4d49a43a39cb92c859))
* **preparation:** preserve unmeasured windows ([1ea7bc8](https://github.com/joaobispo2077/avo/commit/1ea7bc8b53c4008bd8581b4157545fd65c20c95c))
* **craft:** project requested work progress ([c085d14](https://github.com/joaobispo2077/avo/commit/c085d1422a3245a0f731066fa4e92e0fb2c164d3))
* **cutting:** protect uncertain speech in retakes ([d75c8dd](https://github.com/joaobispo2077/avo/commit/d75c8dd6957dd9c19fd5ebd60941a2d29ca52218))
* **artcraft:** publish native provider packages ([009a376](https://github.com/joaobispo2077/avo/commit/009a376934758cb342ddf3afb294fdffcb22be9c))
* **sound:** publish recoverable selections ([e093640](https://github.com/joaobispo2077/avo/commit/e093640086034ef19f68cc3c6b650d407b541e17))
* **exports:** qualify exact editor targets ([b806a95](https://github.com/joaobispo2077/avo/commit/b806a954f70a0b610a6e3c9c1a1dec8555fcb870))
* **sfx:** rank with explicit local encoders ([da2e935](https://github.com/joaobispo2077/avo/commit/da2e9352303f38664b85f4dff79dcca80bc36750))
* **artcraft:** reconcile exact job retries ([a25671a](https://github.com/joaobispo2077/avo/commit/a25671a5d32995dd02c72a020cae7794b0f0ff80))
* **motion:** record recoverable concept choices ([0a496e8](https://github.com/joaobispo2077/avo/commit/0a496e8d296bf5863db309a5c6940d7b5f7d3f71))
* **craft:** record scoped queue decisions ([84d4d79](https://github.com/joaobispo2077/avo/commit/84d4d7934087e0474a4fb8e17f8f94b339e72fa3))
* **camera:** register qualified native transform ([66732d5](https://github.com/joaobispo2077/avo/commit/66732d5843beae343c9e1130075a679fb9f22558))
* **craft:** remember authoring requests ([de87d78](https://github.com/joaobispo2077/avo/commit/de87d78f42fb493e3590d5f708f5f6d66c3b0872))
* **artcraft:** render EffectCraft mask reviews ([b7206ab](https://github.com/joaobispo2077/avo/commit/b7206abf0e9a0a681cac59965b839843e923daa0))
* **sound:** report affected listening ranges ([e02b443](https://github.com/joaobispo2077/avo/commit/e02b4432281f391ae757015bbc49e7ba4af3be1f))
* **sfx:** report affected listening sections ([c9d224c](https://github.com/joaobispo2077/avo/commit/c9d224cd13b1406fdffdf1ecd4fb429017aa1321))
* **sfx:** report exact selected sound overlaps ([771f909](https://github.com/joaobispo2077/avo/commit/771f9094f7ddd2bca644c205ca6b3f9c1d4a8f05))
* **artcraft:** report external source edits ([cf7d04f](https://github.com/joaobispo2077/avo/commit/cf7d04fe6dba0c36de0f671bd13c86035379dffe))
* **reconstruction:** retain ArtCraft job closure ([2cb58fb](https://github.com/joaobispo2077/avo/commit/2cb58fbda64003a7e8c0fdf9b1f1f452aae25acb))
* **motion:** retain disjoint cue direction ([e41dda0](https://github.com/joaobispo2077/avo/commit/e41dda0fb3f06a8727e7256f9147fab715ccef76))
* **motion:** retain exact authoring evidence ([050773d](https://github.com/joaobispo2077/avo/commit/050773dfc6a2b85e0b30a0a5759c54acc924dc1f))
* **artcraft:** retain LightCraft treatments ([d115a92](https://github.com/joaobispo2077/avo/commit/d115a921a8481ee0645d7584117b0439ed41cdf8))
* **sound:** retain measured proof levels ([0a62655](https://github.com/joaobispo2077/avo/commit/0a62655b073491c25ae87c1e64c3a1f9c506f92b))
* **artcraft:** retain native provider sources ([dc061f9](https://github.com/joaobispo2077/avo/commit/dc061f9768c59944544102d1e9af0c85b1d57c65))
* **preparation:** retain note decisions ([4b9f8b1](https://github.com/joaobispo2077/avo/commit/4b9f8b1dc9ed13c02c089e504cdd92b4699e1ef1))
* **preparation:** retain recovery evidence ([be5410d](https://github.com/joaobispo2077/avo/commit/be5410d501df9d8b52ebbe46cb0224be4f8a4f93))
* **motion:** retain scoped application progress ([4d3f201](https://github.com/joaobispo2077/avo/commit/4d3f20199bb266481de7fc51dc707387202ca4e6))
* **exports:** retain selected evidence ([14175c3](https://github.com/joaobispo2077/avo/commit/14175c324e91a64caf8d6f23f5d2f5feb1d19aba))
* **preparation:** retain selected measurements ([cab7246](https://github.com/joaobispo2077/avo/commit/cab7246993813b999d39c8f97dcbaee19026f2e1))
* **sound:** retain selected reconstruction sources ([5307fe7](https://github.com/joaobispo2077/avo/commit/5307fe7def2c4cb169d93aaa7066280483279c5c))
* **sound:** retain selected sound evidence ([01c1137](https://github.com/joaobispo2077/avo/commit/01c1137aaf0f49a4680495b796eaf22ff1b711ce))
* **preparation:** retain word analysis roots ([3666af7](https://github.com/joaobispo2077/avo/commit/3666af75480130469df349466603987d28e2810d))
* **artcraft:** reuse verified native exports ([7582feb](https://github.com/joaobispo2077/avo/commit/7582feb70ba39048d69fc3800e21498d3db36349))
* **artcraft:** revise both AniCraft text slots ([c3b7460](https://github.com/joaobispo2077/avo/commit/c3b74603a46ed0af9f0a975b890e39dd7b1b7bba))
* **exports:** route selected editor trims ([1e72ae2](https://github.com/joaobispo2077/avo/commit/1e72ae227a60abda2dd60e3c962edbad3b3122da))
* **artcraft:** run bounded AniCraft streaming ([064e6f5](https://github.com/joaobispo2077/avo/commit/064e6f5926a57147ded18e6e30ddefd16b3fdcd3))
* **artcraft:** run bounded native jobs ([f3de27d](https://github.com/joaobispo2077/avo/commit/f3de27dd533bfff26fc35dfc22e1c759b725cbf7))
* **artcraft:** run saved-source authoring jobs ([d1ebd72](https://github.com/joaobispo2077/avo/commit/d1ebd72306b3362d3fc86b779eabf2984e7cec35))
* **preparation:** run selected speech recovery ([83843d4](https://github.com/joaobispo2077/avo/commit/83843d48bc9c3e7cb26ee66bc758956acfa9ebcd))
* **artcraft:** scope native readiness reuse ([50daf8e](https://github.com/joaobispo2077/avo/commit/50daf8e40332af589fb02c65d7fb6236bb5f9658))
* **sfx:** search curated descriptions and categories ([2ba01c8](https://github.com/joaobispo2077/avo/commit/2ba01c82e5454cc6c10b4162cfefa9e98e4c5c30))
* **sfx:** seed opt-in scans from favorites ([ff2c039](https://github.com/joaobispo2077/avo/commit/ff2c039bca18bae2103c59bcd0b31d0367fea12d))
* **timeline:** select source mapping occurrence ([6ea8102](https://github.com/joaobispo2077/avo/commit/6ea81023d993a866fd35153aa793f9f601857a7f))
* **preparation:** select transcript evidence ([731262e](https://github.com/joaobispo2077/avo/commit/731262e179daa65693d3caa0436fd32a59309d6e))
* **artcraft:** share approved provider kits ([418d346](https://github.com/joaobispo2077/avo/commit/418d346daf9a46b1589cf3192c88c54abba92386))
* **sound:** show candidate timing fits ([850846c](https://github.com/joaobispo2077/avo/commit/850846c88ae2f81e4e5ebfa3f38f39d1459427dc))
* **review:** show face readiness in both views ([0f5325e](https://github.com/joaobispo2077/avo/commit/0f5325e67fb4efbef1d7cdd5b19537ee9b9caeee))
* **tracks:** show linked review lanes ([7ffaceb](https://github.com/joaobispo2077/avo/commit/7ffaceb772163052a66443a0851665dd9ba15681))
* **motion:** show requested work by default ([8e02660](https://github.com/joaobispo2077/avo/commit/8e026600daf73e4bdcdeeac0d5f7ecc6db8672ab))
* **motion:** show selected camera path states ([9b2db60](https://github.com/joaobispo2077/avo/commit/9b2db60c2c7a3824d0e005541f0079554a1c2b62))
* **motion:** show selected concept direction ([5e72fe8](https://github.com/joaobispo2077/avo/commit/5e72fe864537206d42d620a63ebbac0b2c6d5747))
* **artcraft:** stage AniCraft MCP handoffs ([ead9f9c](https://github.com/joaobispo2077/avo/commit/ead9f9cff9ca3e99c8182ad440e674b0556f7bfe))
* **sfx:** store scoped provider favorites ([545c2e6](https://github.com/joaobispo2077/avo/commit/545c2e64dbfe8d85c7acf071f3af79caa7a12aa9))
* **preparation:** use selected source evidence ([4629097](https://github.com/joaobispo2077/avo/commit/4629097b531c214730799e6d305287b52e6defd9))
* **import:** validate exact FilmCraft returns ([1d3c383](https://github.com/joaobispo2077/avo/commit/1d3c38391c5a37599a41cc92c7e87e6e43b57245))
* **models:** validate optional joint encoders ([a561e4c](https://github.com/joaobispo2077/avo/commit/a561e4c8a7aa27a81cd21440f11dbee4e397292e))
* **sound:** validate selected cue ownership ([cdc1c67](https://github.com/joaobispo2077/avo/commit/cdc1c67df20b020011d3c444e297e4c5c018aa23))
* **motion:** verify anchored camera admission ([1f37d40](https://github.com/joaobispo2077/avo/commit/1f37d40e4520ed358bb09f1e6f1075b9d617a7e5))
* **exports:** verify lossless alpha copies ([ca342fb](https://github.com/joaobispo2077/avo/commit/ca342fb944f2291c99d76b91ae8dadd526e649fc))
* **artcraft:** verify native profile evidence ([4444b55](https://github.com/joaobispo2077/avo/commit/4444b559e0f63bfc511ac60cc88373ba159f92c1))
* **artcraft:** verify retained native packages ([da12f64](https://github.com/joaobispo2077/avo/commit/da12f64ab2336320f79effc337d4bbe30614256e))
* **craft:** wire native and MCP commands ([baea4f2](https://github.com/joaobispo2077/avo/commit/baea4f2d1f1038a517377cb2eafd90b784414373))
* **camera:** wire native proof rendering ([4a2f048](https://github.com/joaobispo2077/avo/commit/4a2f0484dcf9aeea282725c3c33bfb378efcf05f))


### Performance Improvements

* **contracts:** reuse content-bound registries ([a4937a5](https://github.com/joaobispo2077/avo/commit/a4937a51d40e37e0b79a2503d5ecb6f470d29c96))

# [1.22.0](https://github.com/joaobispo2077/avo/compare/v1.21.0...v1.22.0) (2026-11-17)


### Bug Fixes

* **media:** bound historical-output inspection ([83600d9](https://github.com/joaobispo2077/avo/commit/83600d9a81377cc28e4364754fe849bb66bf986a))
* **deps:** patch OpenTelemetry trace parsing ([f55c298](https://github.com/joaobispo2077/avo/commit/f55c298147ef1aef2949a6ceb9362334808734df))
* **schema:** preserve hashes in local schema paths ([bafc1e0](https://github.com/joaobispo2077/avo/commit/bafc1e04e6991deeece7072412af4e6aa07639f2))
* **review:** separate transcription windows ([5c84973](https://github.com/joaobispo2077/avo/commit/5c8497329e9b835b3a7c46deb6064a4a6ae43b5b))


### Features

* **motion:** admit bound HyperFrames assets ([f8947e7](https://github.com/joaobispo2077/avo/commit/f8947e71ed898833266c8b014f65ac8d6af19796))
* **craft:** expose preferences and motion review ([acc1a97](https://github.com/joaobispo2077/avo/commit/acc1a97437704c10fa304d64bf305d72fef522d2))
* **craft:** freeze request choices in pipeline runs ([b9b2356](https://github.com/joaobispo2077/avo/commit/b9b23568e77c4c01e8db9b8e78cf22444e10af76))
* **motion:** project linked motion review ([41d503d](https://github.com/joaobispo2077/avo/commit/41d503d3a75d3ad7ff4c5d736b46218dcfbf2ef7))
* **import:** reconstruct Resolve treatments ([77267c5](https://github.com/joaobispo2077/avo/commit/77267c58518c8994a18178893c5efa35f2b6337d))
* **craft:** resolve scoped editing preferences ([d70c89a](https://github.com/joaobispo2077/avo/commit/d70c89a347a0bc16f63657e28e07afc7a81d36dd))
* **proof:** stream bounded placed renders ([b266cfb](https://github.com/joaobispo2077/avo/commit/b266cfb9e20fb6f7c3c9c912afeea39751880a83))
* **audio:** validate source mix adjustments ([e7697cd](https://github.com/joaobispo2077/avo/commit/e7697cd339b60854dda6467c6e7a370ba19fc4da))

# [1.21.0](https://github.com/joaobispo2077/avo/compare/v1.20.0...v1.21.0) (2026-11-08)


### Bug Fixes

* **ci:** parallelize native unit coverage ([7edfbb6](https://github.com/joaobispo2077/avo/commit/7edfbb6582585a0a70c68b55b6aca10f3a58bff9))
* **render:** reject prior-proof source ancestry ([2b66317](https://github.com/joaobispo2077/avo/commit/2b663171789c252b32e9a6edaf1fafbe7916954c))
* **ci:** restore import and proof checks ([ac74630](https://github.com/joaobispo2077/avo/commit/ac74630bdf85afb9987e23fdba78c1913f1f7361))
* **cleanup:** retain exact import evidence ([169d53d](https://github.com/joaobispo2077/avo/commit/169d53db6935015401fdac6f638f3578040c9792))
* **watch:** retain source context observations ([0cbd428](https://github.com/joaobispo2077/avo/commit/0cbd428b3b9f414ed0151ac92abd6fe012759ca9))
* **timeline:** serialize canonical mutations ([8e99970](https://github.com/joaobispo2077/avo/commit/8e9997010285d0f80509258fc9337574efdc5911))


### Features

* **timeline:** define import layout contracts ([5f0fdfe](https://github.com/joaobispo2077/avo/commit/5f0fdfe73e6ba0eaaa06ba63c7f536001278b574))
* **timeline:** edit placed source layouts ([25a395b](https://github.com/joaobispo2077/avo/commit/25a395b56d85a7503cc675930d6eb8d1fdc6d0d2))
* **pipeline:** expose provider import handoff ([7f5f82f](https://github.com/joaobispo2077/avo/commit/7f5f82fcf576a304dc2980a5fe8c8137b48233f3))
* **import:** find explicit relink candidates ([b73301c](https://github.com/joaobispo2077/avo/commit/b73301c5c713c0b186343a2185cd0f85d6ad21bc))
* **otio:** inspect and normalize exports ([6eef304](https://github.com/joaobispo2077/avo/commit/6eef3043b671e3be1c26dd27a0d44a99664b02cf))
* **otio:** isolate the native reader ([734f72a](https://github.com/joaobispo2077/avo/commit/734f72a1df7b370540de5415fa30efa5f28129de))
* **render:** rebuild placed source timelines ([e9c7fe7](https://github.com/joaobispo2077/avo/commit/e9c7fe7fff864298ac183614540c66bac9b60323))
* **import:** recover exact draft selections ([35b0da4](https://github.com/joaobispo2077/avo/commit/35b0da444d9b2dc2b238c39c03bc9d0fcc74b982))
* **import:** stage and validate handoffs ([80d0221](https://github.com/joaobispo2077/avo/commit/80d0221ba82461d9d5a4228adaffa8071eefad02))
* **media:** verify local original clocks ([a90889c](https://github.com/joaobispo2077/avo/commit/a90889c47ea2198e3e1dafdacf8516538757c419))

# [1.20.0](https://github.com/joaobispo2077/avo/compare/v1.19.1...v1.20.0) (2026-11-04)


### Bug Fixes

* **deps:** align msgpack with develop ([3659184](https://github.com/joaobispo2077/avo/commit/36591845f0ec896ed6c26d3e006f4dc007d52d1b))
* **deps:** patch msgpack parser vulnerability ([64a289f](https://github.com/joaobispo2077/avo/commit/64a289f9ac91bdbf5fd3da1fbb790344978cd626))
* **proof:** preserve AAC sample boundaries ([4eb85c6](https://github.com/joaobispo2077/avo/commit/4eb85c6df707fb0457319276f8f18c4262cfea7b))
* **audio:** preserve finite ducked bed tails ([27623e1](https://github.com/joaobispo2077/avo/commit/27623e155fb675f01848a2edfaa0850bd84f84bf))
* **cutting:** reconstruct native mixed references ([a3453e0](https://github.com/joaobispo2077/avo/commit/a3453e0b3f91f34db7e1447ba2ac7e767fff5315))
* **review:** restrict window scans to risk windows ([116bf5b](https://github.com/joaobispo2077/avo/commit/116bf5b371ea7db89fb4dc01605031aa71ec1c66))


### Features

* **costs:** activate typed accounting lifecycle ([42a562b](https://github.com/joaobispo2077/avo/commit/42a562b33cb70a9884548bf6f366f30ba6e26b18))
* **costs:** admit typed ledger packets ([c1ba50a](https://github.com/joaobispo2077/avo/commit/c1ba50ab01ba855e685ec40db5ebafd152d40091))
* **costs:** collect scoped host evidence ([a8d853b](https://github.com/joaobispo2077/avo/commit/a8d853b1f3c968cf7f12fcf5c4aa01bbfcb01667))
* **costs:** define typed evidence contracts ([f59bb70](https://github.com/joaobispo2077/avo/commit/f59bb70d2f7b9e073fda468bf83470ed148675e3))
* **costs:** estimate offline usage and value ([0ae9005](https://github.com/joaobispo2077/avo/commit/0ae90058169836c7adab81ccf3342b409d6abc35))
* **costs:** export portable accounting history ([6848b1e](https://github.com/joaobispo2077/avo/commit/6848b1edc087fef72a4060765c2b737ed6bc1156))
* **costs:** expose host accounting controls ([27b78fe](https://github.com/joaobispo2077/avo/commit/27b78fe7abce38ef1e8cc4e6af49622bc7f95ef2))
* **costs:** model host participation graphs ([4bb64e6](https://github.com/joaobispo2077/avo/commit/4bb64e6dccf5e64f1abffd9506b3a1fd904d94c1))
* **costs:** normalize owned response evidence ([9fb033b](https://github.com/joaobispo2077/avo/commit/9fb033b62334952b801cafae734222f0d2d2e6e5))
* **costs:** project coverage and closure reports ([3c0fe76](https://github.com/joaobispo2077/avo/commit/3c0fe76fb28a07f97b903815568bfe183763a2bd))
* **costs:** reconcile evidence and allocations ([b685fbe](https://github.com/joaobispo2077/avo/commit/b685fbe96c9841d88664bd7640b39e7af7845106))


### Performance Improvements

* **cutting:** reuse validated analysis per batch ([06a61f7](https://github.com/joaobispo2077/avo/commit/06a61f7a87bf32a213e251e0376498cd042513ef))
* **cutting:** skip context for retained pauses ([ae177e5](https://github.com/joaobispo2077/avo/commit/ae177e5f94ebb58ec193f817cb76697e53ac3928))

## [1.19.1](https://github.com/joaobispo2077/avo/compare/v1.19.0...v1.19.1) (2026-10-31)


### Bug Fixes

* **motion:** stop encoder descendants on cancel ([1afb175](https://github.com/joaobispo2077/avo/commit/1afb1751ef4b803daf5e00d94760587f4a6a4f96))


### Performance Improvements

* **motion:** reuse encoded frames for seek checks ([20fec61](https://github.com/joaobispo2077/avo/commit/20fec61e9eb294468c200ce94dfb8d4a80e6add8))

# [1.19.0](https://github.com/joaobispo2077/avo/compare/v1.18.0...v1.19.0) (2026-10-31)


### Bug Fixes

* **deps:** bump msgpack to 1.2.4 ([46d72e2](https://github.com/joaobispo2077/avo/commit/46d72e25d420c39bc1c4869d94cc40893be494db))
* **tracks:** compare cue clocks exactly ([9c8d730](https://github.com/joaobispo2077/avo/commit/9c8d73045d2cf89e27f6cbabcce5517067766596))
* **setup:** fail early when Python is below 3.11 ([affa69f](https://github.com/joaobispo2077/avo/commit/affa69ff19de94335fd6b1bf9daee59e6beb0a44))
* **cutting:** harden native proof verification ([0a0bd50](https://github.com/joaobispo2077/avo/commit/0a0bd50039872e93b077c2f0f975639494e74143))
* **brush:** keep starters deterministic in software ([2bbfdf1](https://github.com/joaobispo2077/avo/commit/2bbfdf1aaa0fff736beb4a689158ac2a84e7e535))
* **install:** map official skill agent IDs ([c365592](https://github.com/joaobispo2077/avo/commit/c36559274ad4e90c9b48b0657a418048e20247cb))
* **schema:** resolve cutting references locally ([aed67d6](https://github.com/joaobispo2077/avo/commit/aed67d6ef5df5e9de59c159e0cbfbb0513e370db))
* **code-drawn:** restore cross-platform checks ([5b2f2e9](https://github.com/joaobispo2077/avo/commit/5b2f2e9349d9958834820c08ad75ba284e191574))
* **ci:** restore workflow validation ([beb765e](https://github.com/joaobispo2077/avo/commit/beb765e0d936d2795c07dde3d1e0abe811946214))
* **shorts:** retain unchanged item review state ([d4c73a0](https://github.com/joaobispo2077/avo/commit/d4c73a0d1d0a505f6477caa23ea9673fa95176b7))


### Features

* **library:** add approved recoverable moves ([bd306d8](https://github.com/joaobispo2077/avo/commit/bd306d84461414457363207219a8b1b01fa82ad4))
* **library:** add bounded local ASR batches ([d578624](https://github.com/joaobispo2077/avo/commit/d578624a5c63a55f18559ebb3b5c3dbb38cf5a76))
* **code-drawn:** add editable drawing starters ([90fc34f](https://github.com/joaobispo2077/avo/commit/90fc34f99299525e930a3c390ba803b42ae4cbc1))
* **library:** add editable folder previews ([e374128](https://github.com/joaobispo2077/avo/commit/e37412899b9926e7d835a371f7768b11a6f33632))
* **library:** add immutable library records ([b27c65e](https://github.com/joaobispo2077/avo/commit/b27c65ea7b523920a561d596feceb0a72bb13e12))
* **motion:** add scoped engine preferences ([3afd30e](https://github.com/joaobispo2077/avo/commit/3afd30e01c8b60b2face682289fbd4ba7217d905))
* **library:** add source-bound footage search ([88a80ca](https://github.com/joaobispo2077/avo/commit/88a80cae613d9fb16ef895f987aae9d6d7aec4d1))
* **timeline:** admit canonical motion assets ([998a6fa](https://github.com/joaobispo2077/avo/commit/998a6fa782b98bf4ca2bf3a6903cd4136c041b35))
* **audio:** apply approved dialogue treatment ([0561a67](https://github.com/joaobispo2077/avo/commit/0561a67c9d3999e37f3c55b2bdb26f2574b60fbc))
* **proof:** bind generated event visibility ([ff13ddf](https://github.com/joaobispo2077/avo/commit/ff13ddf4a3b832c7c212a2bfda5c9b7348962b1b))
* **code-drawn:** capture seekable browser frames ([ab70e78](https://github.com/joaobispo2077/avo/commit/ab70e78d51a441cbbaffb2b187aa9d2675692749))
* **proof:** composite generated motion ([63c9c7a](https://github.com/joaobispo2077/avo/commit/63c9c7ae02aaae322901246903b1c738b10264b5))
* **code-drawn:** define frozen source contracts ([f6a6c8f](https://github.com/joaobispo2077/avo/commit/f6a6c8f96af1e3b9bb7c25b5f39fa73a1f3afb29))
* **cli:** expose native motion workflows ([a023744](https://github.com/joaobispo2077/avo/commit/a02374463e99ccce6a84e09f59ef4f0e94de663c))
* **library:** expose native organize commands ([324d9a2](https://github.com/joaobispo2077/avo/commit/324d9a270c5405c4b8819976892ea016c08319b4))
* **proof:** mix declared finite audio sources ([c9b9a20](https://github.com/joaobispo2077/avo/commit/c9b9a203291a326727fa3da11293ef65ad745fc8))
* **shorts:** render admitted drawing overlays ([5d38054](https://github.com/joaobispo2077/avo/commit/5d38054a9e888a5a1fbe0d40920921d1b2d06317))
* **pipeline:** retain drawing source closures ([8f48937](https://github.com/joaobispo2077/avo/commit/8f4893737791ffc8a3104acf1c22975ce7708e16))
* **review:** verify native motion delivery ([640d2d0](https://github.com/joaobispo2077/avo/commit/640d2d0cadf0b5dd1c43b2f362c20420417a66cb))


### Performance Improvements

* **proof:** bound representative risk windows ([45eb71e](https://github.com/joaobispo2077/avo/commit/45eb71e62d52e536debdf0df61a4d84a6aebe592))
* **proof:** reuse immutable validation work ([dae7185](https://github.com/joaobispo2077/avo/commit/dae7185e07f68bfb07ca86efac997feeec6ba86c))
* **telemetry:** skip unused model discovery ([f7bdfc4](https://github.com/joaobispo2077/avo/commit/f7bdfc4493ef78f800c2d96bf8ba9d3526d531fe))

# [1.18.0](https://github.com/joaobispo2077/avo/compare/v1.17.1...v1.18.0) (2026-10-25)


### Bug Fixes

* **quality:** name three high advisories in the yellow audit cell ([930b8eb](https://github.com/joaobispo2077/avo/commit/930b8eb8a102316c6c0554c0a059ea1c671caae0))


### Features

* **quality:** color dependency audit by unwaived severity ([520d9f5](https://github.com/joaobispo2077/avo/commit/520d9f58dab5b5010ca35da58f8e58970302ba28))

## [1.17.1](https://github.com/joaobispo2077/avo/compare/v1.17.0...v1.17.1) (2026-10-24)


### Bug Fixes

* **ci:** publish releases after successful builds ([c0e1740](https://github.com/joaobispo2077/avo/commit/c0e17401fd630e94046739bc292e39b7dc457b4c))

# [1.17.0](https://github.com/joaobispo2077/avo/compare/v1.16.0...v1.17.0) (2026-10-24)


### Bug Fixes

* **deps:** bump filelock and setuptools for pip-audit ([d276865](https://github.com/joaobispo2077/avo/commit/d27686552668ac6ff9fbfee2d6f942a956a6249a))
* **deps:** bump pillow to 13.0.0 and certifi to 2026.10.19 ([755af61](https://github.com/joaobispo2077/avo/commit/755af6124477ffe2eb4550418080b3444148f275))
* **schema:** find installed validation contracts ([8d46b1a](https://github.com/joaobispo2077/avo/commit/8d46b1a8b114e71fed19a1755119f89dd80039c9))
* **delivery:** locate documented final masters ([2805a6c](https://github.com/joaobispo2077/avo/commit/2805a6c9979910196bbda921d53441f8359ecd34))
* **shorts:** preserve protected audio samples ([39d6e3a](https://github.com/joaobispo2077/avo/commit/39d6e3a14c41193d7bec375fc78046ee1f5b937e))
* **cleanup:** resolve Shorts delivery sidecars ([9150a8a](https://github.com/joaobispo2077/avo/commit/9150a8a1d1dff28d7e30f620e56e879372a6b29f))
* **reconstruction:** separate history from media ([5543e25](https://github.com/joaobispo2077/avo/commit/5543e25f922869e1273314b649b84db117d3f069))
* **pipeline:** tolerate unavailable learning ([a7c7dd9](https://github.com/joaobispo2077/avo/commit/a7c7dd957ce136f7077daa6845e4025c121ad802))
* **cleanup:** verify dependencies once per run ([0aa1763](https://github.com/joaobispo2077/avo/commit/0aa17633d670968ba719deefb2b37b87f1a3a1ca))
* **qc:** verify persisted assembly lineage ([356f433](https://github.com/joaobispo2077/avo/commit/356f433ac0691145d9f42c141c338c7e4bdc3da1))


### Features

* **mcp:** add exact creative review tools ([02e9739](https://github.com/joaobispo2077/avo/commit/02e9739b4032016b3d5f315c7e09ad29a2db57d6))
* **delivery:** adopt reviewed existing masters ([fa51dd0](https://github.com/joaobispo2077/avo/commit/fa51dd02ee805b249b168bb3d59f9dd6e0ad0e07))
* **review:** bind serial Shorts scorecards ([73fb589](https://github.com/joaobispo2077/avo/commit/73fb58932d42fe393387c404bd3c3d4593565428))
* **preservation:** close without deleting files ([5632663](https://github.com/joaobispo2077/avo/commit/563266308b76c2a83f3693049362dda544ba0f9a))
* **costs:** collect agent and review usage ([67b9c83](https://github.com/joaobispo2077/avo/commit/67b9c83e3fdc9fd56fbe07455dd8c5be54c853a9))
* **direction:** collect bounded learning evidence ([02c62ce](https://github.com/joaobispo2077/avo/commit/02c62ce278b5a6528f8b9b63d7498a38e1202f07))
* **shorts:** compile timed graphics layers ([a4711d6](https://github.com/joaobispo2077/avo/commit/a4711d610b7d64a235ce7ecc4e28688e41254319))
* **costs:** define identity and snapshot contracts ([f981a52](https://github.com/joaobispo2077/avo/commit/f981a5238bcc70eaaed5b742852e3f358ebe68b1))
* **briefstart:** define project choice contract ([91ada5a](https://github.com/joaobispo2077/avo/commit/91ada5a05b2e56a0ed622e2778411eec17c4dca6))
* **direction:** define provider review contract ([ef9cce1](https://github.com/joaobispo2077/avo/commit/ef9cce1355dbe8ca5a9896871eb8d5d1d8023d7c))
* **costs:** define usage and tariff contracts ([bab45c2](https://github.com/joaobispo2077/avo/commit/bab45c2dd20fbfa2a8455161d50bb7ad45244ebe))
* **costs:** enable agent cost workflows ([a8d62d8](https://github.com/joaobispo2077/avo/commit/a8d62d813fb9ea0371427db0c114973e503a0b5d))
* **costs:** expose CLI and MCP operations ([e1ca93c](https://github.com/joaobispo2077/avo/commit/e1ca93c6c9d5bc40938fe86b67adba15aa94f023))
* **cli:** expose direction and briefstart ([a4957dd](https://github.com/joaobispo2077/avo/commit/a4957dde74ec3d2e0136aa24b3d485ea2fda51e4))
* **shorts:** extend versioned proof contracts ([3c6a644](https://github.com/joaobispo2077/avo/commit/3c6a644246d0b7dc0087df48433a9322a59effe2))
* **direction:** manage reviewed provider profiles ([9a600f4](https://github.com/joaobispo2077/avo/commit/9a600f4f1204344ed874da2542d561ea19dfdbe3))
* **briefstart:** offer scoped creative choices ([5ebed3d](https://github.com/joaobispo2077/avo/commit/5ebed3d1174844b9f8ae3c77a18e185181cd5d5b))
* **pipeline:** offer selected creative guidance ([fb6d26c](https://github.com/joaobispo2077/avo/commit/fb6d26c881d751fc06082dd5200e0df491168c26))
* **direction:** persist exact creative decisions ([a31d3ab](https://github.com/joaobispo2077/avo/commit/a31d3abbb61bde8c341c986335957c79f8da947e))
* **costs:** persist immutable usage evidence ([c0b6e72](https://github.com/joaobispo2077/avo/commit/c0b6e726828ab7b78e93e23c6583a8b67cf06e1a))
* **shorts:** prepare dialogue and audio beds ([4d3fb6e](https://github.com/joaobispo2077/avo/commit/4d3fb6eb3ae29671e18d893cfba3bc510be9ca0f))
* **shorts:** render original-source proofs ([e95b046](https://github.com/joaobispo2077/avo/commit/e95b04645a551b74a6d23e004c3879085452bedd))
* **costs:** report usage and retained history ([6ce2113](https://github.com/joaobispo2077/avo/commit/6ce21137a7d960e112b1721f37b1cea290e758c9))
* **shorts:** resolve timed visuals and audio ([2297c23](https://github.com/joaobispo2077/avo/commit/2297c2357c44cd1bfbdacda958e50fe37a365c35))
* **costs:** retain costs through video closure ([4323f0a](https://github.com/joaobispo2077/avo/commit/4323f0a88135c5364e5393535f61004ee82914d8))
* **review:** reuse exact candidate transcripts ([1f898da](https://github.com/joaobispo2077/avo/commit/1f898dacc580950ebf2222415a50d2d688d52056))
* **shorts:** wire proof and review orchestration ([60abc2a](https://github.com/joaobispo2077/avo/commit/60abc2a684606e2f7ad354ceedc550cf1a2bb585))


### Performance Improvements

* **schema:** cache validators by content ([7be3def](https://github.com/joaobispo2077/avo/commit/7be3defc80e4946cba78b8d8add5aa91c8ffee7a))
* **watch:** decode review frames in one pass ([ceabcbb](https://github.com/joaobispo2077/avo/commit/ceabcbb9ba99c260c640712c41243340e547b83b))

# [1.16.0](https://github.com/joaobispo2077/avo/compare/v1.15.0...v1.16.0) (2026-10-18)


### Bug Fixes

* **ci:** add conservative run selection ([4757b06](https://github.com/joaobispo2077/avo/commit/4757b061adc024093f475463e76600de4e94b207))
* **quality:** normalize mutation export paths ([210e50e](https://github.com/joaobispo2077/avo/commit/210e50e15af5f4f45f8b767db77579df0c0c83a9))
* **quality:** preserve frozen report readout ([11564e8](https://github.com/joaobispo2077/avo/commit/11564e8dcde68787cf4c3b3386b1bdf47ab26a5d))
* **quality:** restore threshold chart colors ([f8f55c3](https://github.com/joaobispo2077/avo/commit/f8f55c37df5f77bb8b9e6c8ed836e1bc06317413))


### Features

* **quality:** add indexed review renderers ([b641ff9](https://github.com/joaobispo2077/avo/commit/b641ff96a9a4f18efd05aba73399acaf02fd0aae))
* **quality:** assemble readable run reports ([529d627](https://github.com/joaobispo2077/avo/commit/529d627a8840c55487bf80ffafed819d5d5f8af1))
* **quality:** bind supporting report evidence ([a453530](https://github.com/joaobispo2077/avo/commit/a45353025cc2a003a478501243f6f817556c11fd))
* **quality:** freeze metric definitions ([849f81f](https://github.com/joaobispo2077/avo/commit/849f81f126595d6ce03fdc8ec5df8de3c618d9d7))
* **quality:** render mutation and gate views ([9b7271f](https://github.com/joaobispo2077/avo/commit/9b7271f46128b41d53ab09cb7d5c612a3eeaf276))
* **quality:** retain per-source mutation data ([62dc010](https://github.com/joaobispo2077/avo/commit/62dc010dfa7b376c5f03b46459971daed85440fd))
* **ci:** support additional chart roles ([4e704e3](https://github.com/joaobispo2077/avo/commit/4e704e3a539ae402adbc67c7337690febef1016b))
* **ci:** support bounded quality chart roles ([1abd393](https://github.com/joaobispo2077/avo/commit/1abd3935c6602739a4a654668ac1ebd0d839eee4))
* **quality:** verify file and function evidence ([7554445](https://github.com/joaobispo2077/avo/commit/7554445ac53b5b4921836bcc29a25886b1aedf00))

# [1.15.0](https://github.com/joaobispo2077/avo/compare/v1.14.0...v1.15.0) (2026-10-16)


### Bug Fixes

* **vision:** bound native review findings ([bf0271d](https://github.com/joaobispo2077/avo/commit/bf0271d1e1a6f9b41f9494467c97ee085c22bedf))
* **mutation:** reject incomplete mutation runs ([5247f78](https://github.com/joaobispo2077/avo/commit/5247f78a0fc2373a29f860915d29e173e71a1a5a))
* **quality:** replace chart commits with links ([dbc5026](https://github.com/joaobispo2077/avo/commit/dbc5026e7235071f86cea3684a0fd5805841515b))
* **release:** require matching quality evidence ([de15454](https://github.com/joaobispo2077/avo/commit/de15454145d55ffb9c259d1e85f8e29264aa12fb))
* **deps:** require patched MCP 2.2 runtime ([ca5fc42](https://github.com/joaobispo2077/avo/commit/ca5fc42850c038a27b09f505994f8304ccc30cc7)), closes [#98](https://github.com/joaobispo2077/avo/issues/98)
* **deps:** resolve internal import dependencies ([f4af954](https://github.com/joaobispo2077/avo/commit/f4af954992808c766675f3c8fa98f5d73a02d6a6))
* **quality:** restore inline dashboard images ([cb11fbf](https://github.com/joaobispo2077/avo/commit/cb11fbf96d7609197a69651284e860418e1dd3fa)), closes [#98](https://github.com/joaobispo2077/avo/issues/98)


### Features

* **quality:** add compact normalized dashboard ([cfa3076](https://github.com/joaobispo2077/avo/commit/cfa30767475017bdfb92a11b9932dbf29cf71a08))
* **ci:** aggregate required quality evidence ([dd358d5](https://github.com/joaobispo2077/avo/commit/dd358d50930f434464a234680f1abf0ab32188d8))
* **quality:** measure CRAP and coupling ([8ae6fc8](https://github.com/joaobispo2077/avo/commit/8ae6fc80dc92868275e4de9a7bef38626829ca37))
* **quality:** normalize verified metrics ([359d4ca](https://github.com/joaobispo2077/avo/commit/359d4ca44c65cdc6ed4034f697b96b0f426fc932))
* **safety:** report critical branch coverage ([305d8ef](https://github.com/joaobispo2077/avo/commit/305d8ef74aca84a391318fe29937c66b7ec91c53))
* **quality:** retain actual analyzer findings ([e10ef35](https://github.com/joaobispo2077/avo/commit/e10ef35e4f3e42cfc1bcbcb8ed92c578d0c6eee8))
* **reporting:** separate metrics and decisions ([818130c](https://github.com/joaobispo2077/avo/commit/818130cd6af8caee3764b5a3e3fe4f83939d82a7))

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
