"""Frozen schema fingerprints for release 20260930_0008."""

RELEASE_SCHEMA_SHA256: dict[tuple[str, str, str], str] = {
    (
        "table",
        "alembic_version",
        "alembic_version",
    ): "c85bfd889cff304bc45779b35249633db07627c6e27322efb0b63bdc0ac77ca4",
    (
        "table",
        "players",
        "players",
    ): "9a0c44ee98b8a39607cc845d61d5bc47bc84413d1f015179f1f84d0900d5982a",
    (
        "table",
        "operations_transport_requests",
        "operations_transport_requests",
    ): "da79dba70a1bf34eab08deac047b27a63aef37fd95d78503f3a36498d87ce9e1",
    (
        "index",
        "ix_operations_transport_requests_retain_until",
        "operations_transport_requests",
    ): "d33c03cc142afb98120659da33788a4b73715fe79c77cd8b167378d3f41ca754",
    (
        "table",
        "economy_accounts",
        "economy_accounts",
    ): "63a7dd949164e9cd47df9991cda3f43c69fe1cd38f8b1105beacc211b1585b11",
    (
        "table",
        "economy_account_balances",
        "economy_account_balances",
    ): "6ee87d7de6f16c825228338935a4f377dcb6db2d77671a73486e3a2db37b4020",
    (
        "table",
        "operations_integrity_violations",
        "operations_integrity_violations",
    ): "d02700327ca1933c329d4551090d14029a916aaa9760991ebdc38b7237372553",
    (
        "index",
        "ix_operations_integrity_violations_aggregate_id",
        "operations_integrity_violations",
    ): "855a642543b34165617efeef4475cd1010553fd499f617d26b1bd5a9685e256a",
    (
        "trigger",
        "trg_players_require_wallet_after_insert",
        "players",
    ): "d10ba249fcaa1a95a746b161f00dac7550284f4f47cc27acdf0e5b6a4f212d2c",
    (
        "trigger",
        "trg_players_integrity_after_delete",
        "players",
    ): "5a2112e3c1f14116a67adf1c9549e8e6dc29fb9eb995d616bd53632a994b1087",
    (
        "trigger",
        "trg_accounts_require_balance_after_insert",
        "economy_accounts",
    ): "e804ee95f1c79daba38da626c82aec2305cc1939dc63ecb7b7fc8867ebbf52a8",
    (
        "trigger",
        "trg_accounts_integrity_after_delete",
        "economy_accounts",
    ): "ddf839e5d880522d77be0398fc109c2c79fd7a7d201f12f2ce951fb81222b94d",
    (
        "trigger",
        "trg_balances_complete_account_after_insert",
        "economy_account_balances",
    ): "e70fefabb22b630ec90f41e74bd9e370d3449719fe1ba7cd474dbb1a00a3213c",
    (
        "trigger",
        "trg_balances_integrity_after_delete",
        "economy_account_balances",
    ): "61f22109e8c548861118d56a425613ebe9429ac2279589949e2fdc8408ed9d33",
    (
        "trigger",
        "trg_integrity_violations_protect_active_delete",
        "operations_integrity_violations",
    ): "bb31f1a98bb40c5f0aeab43d0120822051c3d734e8d3d130756ef10a479c081c",
    (
        "trigger",
        "trg_integrity_violations_protect_update",
        "operations_integrity_violations",
    ): "498f8213c671f5b45195db4905705c435c66397eb6e6b14a04d78a43a8b12c4f",
    (
        "table",
        "economy_ledger_transactions",
        "economy_ledger_transactions",
    ): "22f7cf10c35ea7eb598ed1f971a39cce7eb05bcd2ec031c111bd5966942d2702",
    (
        "index",
        "ix_economy_ledger_transactions_committed_order",
        "economy_ledger_transactions",
    ): "ce0a4f5bf6981ddea8486915f997080aca0eb3afdc4736840fd769a62bb0eeaf",
    (
        "table",
        "economy_ledger_postings",
        "economy_ledger_postings",
    ): "1acda03f18fbc4e43c86581da2a46537a4b9f780dda0de38c52f632ffa290327",
    (
        "trigger",
        "trg_players_immutable_identity",
        "players",
    ): "e2e0b8fa15a0542e091800f3874081102db8f4db87e4ecf54f8b356e22aff192",
    (
        "trigger",
        "trg_economy_accounts_immutable_identity",
        "economy_accounts",
    ): "0992d674c96b3232c3a3decd00e297d0c02e19896ba35291590a2db61e136a38",
    (
        "trigger",
        "trg_economy_account_balances_immutable_identity",
        "economy_account_balances",
    ): "ed77c4259f8b0c115b5d6dee09268282b3e390c265e4f000336279fbe84d5eda",
    (
        "trigger",
        "trg_players_reject_conflicting_insert",
        "players",
    ): "b1eef8282a1422f7452155c631b201dcf5a3bf149a561e41c5c0b562a74af9d5",
    (
        "trigger",
        "trg_accounts_reject_conflicting_insert",
        "economy_accounts",
    ): "4dccf0930e18d81a4a9171dedf84b19bb23996c69540a08a44cfa97cb90f356f",
    (
        "trigger",
        "trg_balances_reject_conflicting_insert",
        "economy_account_balances",
    ): "bff25719bf0d35802fd715eb3024dc4df88c3d161c139bed7fc29d7aada66294",
    (
        "table",
        "safety_access_audit",
        "safety_access_audit",
    ): "9973a24c11a6f5d2b634bcf61ec11317a9581c7e8dd3bff116697bb09324f236",
    (
        "index",
        "ix_safety_audit_created",
        "safety_access_audit",
    ): "511208c0d5249a69c1b6cea3e97d87e629cf8179e477391c091ddf37a533f9f2",
    (
        "table",
        "safety_bootstrap",
        "safety_bootstrap",
    ): "9ea9d791863b85441fed618f7ba7e5078805913ace46081eb9b79dd61dda9303",
    (
        "table",
        "safety_proposals",
        "safety_proposals",
    ): "30dd7d48662a2e029607f3e2bbd3d34763e1b4da25f4af898a2647f25774749a",
    (
        "index",
        "ix_safety_proposals_actor_time",
        "safety_proposals",
    ): "5f02172d9fb1b10f472a005da1782e53c07fd941c4a64f55bd9804626ea1ac66",
    (
        "table",
        "safety_restrictions",
        "safety_restrictions",
    ): "f7cbc1696264d00d0ca393cc493820e7c57f3407dff44f2dc2c7e77770629220",
    (
        "table",
        "safety_proposal_targets",
        "safety_proposal_targets",
    ): "f41e3a987b536291f5efe5a8462452590cd2c1c12ed4bdc91565c5d569721362",
    (
        "trigger",
        "trg_safety_access_audit_no_replace",
        "safety_access_audit",
    ): "e90b9831abec5134b6429b2a95ba11eb2a649888e00a86d6b47c7c13616d6e46",
    (
        "trigger",
        "trg_safety_access_audit_no_delete",
        "safety_access_audit",
    ): "dc07f7dc4caf08263eac0658cf488a58d6fefa687a28f2db788c3360313d0899",
    (
        "trigger",
        "trg_safety_access_audit_no_update",
        "safety_access_audit",
    ): "aaf19ea70e133597bd2987182de096af1ed71eccc7127f7c2f781da1098b44b3",
    (
        "trigger",
        "trg_safety_bootstrap_no_replace",
        "safety_bootstrap",
    ): "2d331c4b6219db8fb9612465e4c4bf4cfb542c5e10c48050ed82b6e8b413ee7a",
    (
        "trigger",
        "trg_safety_bootstrap_no_delete",
        "safety_bootstrap",
    ): "41f8686cd3b116216687a3fa3b23c6da8392a5bd79a6aaa9ddae2d24665574e6",
    (
        "trigger",
        "trg_safety_bootstrap_no_update",
        "safety_bootstrap",
    ): "2c384be66803fe9547e38529ad7cf563902583959ad70c7ba204b8bba559b1a4",
    (
        "trigger",
        "trg_safety_proposals_no_replace",
        "safety_proposals",
    ): "f1e10fdee3ad8a9e2a46a7c358cc21b993b6608198c81bc46cba420e9c5961cf",
    (
        "trigger",
        "trg_safety_proposals_no_delete",
        "safety_proposals",
    ): "e78bdbbd251324a0a26f7d1b407a15a25ebd8d512bdeb73574cb8e69f7c008ba",
    (
        "trigger",
        "trg_safety_proposal_targets_no_replace",
        "safety_proposal_targets",
    ): "b756c2060fe1c61e857047257445a81865f75fe7c729859738e347878ccfc238",
    (
        "trigger",
        "trg_safety_proposal_targets_no_delete",
        "safety_proposal_targets",
    ): "dc4c0a5b9f0683020f18d4a9b433242eca7343153d1d4f38bc313d3b9e084cf9",
    (
        "trigger",
        "trg_safety_proposal_targets_no_update",
        "safety_proposal_targets",
    ): "acac3b7b36faa080b2b40a082535ec47f1a39641bf614d7b1dff8485f99359f4",
    (
        "trigger",
        "trg_safety_proposals_transition",
        "safety_proposals",
    ): "f2b9d95e93132c360c0916113082461eb478e8459f2bdb55f7818317a4d7bca4",
    (
        "table",
        "safety_proposal_scopes",
        "safety_proposal_scopes",
    ): "0b4aaed17796f345f3b082b9a26905486b026b652e31daad458a23f60030d2d2",
    (
        "trigger",
        "trg_safety_scope_no_replace",
        "safety_proposal_scopes",
    ): "88515a20dafe6a163d2f57553b3b8737cd67b0f628662205abfe160892400c20",
    (
        "trigger",
        "trg_safety_scope_no_update",
        "safety_proposal_scopes",
    ): "ac987cca1944be8021baf6f3a4ebff68c374516daad16f7c834af2b91861cb12",
    (
        "trigger",
        "trg_safety_scope_no_delete",
        "safety_proposal_scopes",
    ): "069e2f7a317cb0b55e5487e0d53e4641a9eb0b3e53479638d7dc61f5a231a544",
    (
        "trigger",
        "trg_safety_targets_sealed",
        "safety_proposal_targets",
    ): "2810b294188d52975b5d7919dbd02d653ea9885d1f61c60bff692fba1070bc25",
    (
        "trigger",
        "trg_safety_scope_validate",
        "safety_proposal_scopes",
    ): "3d844cd00b7fd5cb66fa583dffc3fcb6f2a9709e0e39b830f4d4a1d2e05a54a8",
    (
        "trigger",
        "trg_safety_proposal_initial_state",
        "safety_proposals",
    ): "58fab1aff6ad183a62b70131850b9e1fce1fa3f8a6eb6c53390664a65df7a08f",
    (
        "trigger",
        "trg_safety_proposal_require_scope",
        "safety_proposals",
    ): "46d333ef4d1b045f07d4d7b994515db038250815d74f8e617e74ddaa5b3b67da",
    (
        "table",
        "economy_grant_executions",
        "economy_grant_executions",
    ): "8825fbf9c2be46bac041be2b4c860cfec03b8d01f5d0dd18764fe4be8c352d9d",
    (
        "index",
        "ix_grant_execution_actor_time",
        "economy_grant_executions",
    ): "4cc9f3b1990f2e08eb213c323fa4998d9d6b1df5ef973e02f38be9328b69b51f",
    (
        "table",
        "economy_grant_targets",
        "economy_grant_targets",
    ): "4996e23e7bb50e5d2b065afd5b0c09efb3771bfe18d39d9bf6444aea2ffaee25",
    (
        "trigger",
        "trg_economy_grant_executions_update",
        "economy_grant_executions",
    ): "0642eb7223bb45da469b10cd7b37422a8c5875c5d0374b1fb8e1096902a72471",
    (
        "trigger",
        "trg_economy_grant_executions_delete",
        "economy_grant_executions",
    ): "e4fdcb93c62b5483025980619008af2b75ca22cdacf5a5922bc8a86f9d1063f3",
    (
        "trigger",
        "trg_economy_grant_executions_replace",
        "economy_grant_executions",
    ): "0056ed50f93c31b07e7d2921aef3d98cd385ebbf6cba07c46a7699c95193f142",
    (
        "trigger",
        "trg_economy_grant_targets_update",
        "economy_grant_targets",
    ): "b1085a2b0e80e8017bc402eab83c64504c7a0c50f48f7ffee3d5b4e68ccb463d",
    (
        "trigger",
        "trg_economy_grant_targets_delete",
        "economy_grant_targets",
    ): "8889afd55dd339dcbe1263baff2ed04277c3b1ce852e5f0f7e67bc2d6b75012f",
    (
        "trigger",
        "trg_economy_grant_targets_replace",
        "economy_grant_targets",
    ): "87a1f041a05eb884ff9e6f2224b72455861d1e0e921f6cd393e9e4b21234df6d",
    (
        "trigger",
        "trg_grant_targets_sealed",
        "economy_grant_targets",
    ): "9ce248fb34b400c20ee21f02be48d3a2e60abe1c432326bb81019c3d5a5e8b48",
    (
        "trigger",
        "trg_grant_ledger_update",
        "economy_ledger_transactions",
    ): "2958c4adedee1b0f7094fa942c9ba5b0ca41fefedbc26a869ee374f26b358395",
    (
        "trigger",
        "trg_grant_postings_update",
        "economy_ledger_postings",
    ): "ec42dbfbc822a4e5178a4f60ea4d37ef94528d53ed3fc28309d4db67746835a5",
    (
        "trigger",
        "trg_grant_ledger_delete",
        "economy_ledger_transactions",
    ): "de822913cf46419f08a6ec6651c213f839cf03e0b47a6c6be8a458e00b6f1ae3",
    (
        "trigger",
        "trg_grant_postings_delete",
        "economy_ledger_postings",
    ): "18b1f89484cf4e4dad733632e8ee728de7fa97ed912f1dd5987000f3f5eb3f0a",
    (
        "trigger",
        "trg_grant_ledger_replace",
        "economy_ledger_transactions",
    ): "22077b3b7a2f4917ebbd318ebc8fdef68f88a2096d66b6863ff82695a14d19cc",
    (
        "trigger",
        "trg_grant_postings_sealed",
        "economy_ledger_postings",
    ): "e620a5282b455dc78d0cc7730f9e9a56de6d4ea9448257b7b8cb9f91cabc94d2",
    (
        "trigger",
        "trg_grant_execution_validate",
        "economy_grant_executions",
    ): "d9e209a2dd4c23c76c45b3fdd11602c29c4d2bb73d43a1fa7d8cf2b737a23fca",
    (
        "trigger",
        "trg_grant_postings_incoming_update",
        "economy_ledger_postings",
    ): "59e67a11e88f3b40d29b9744d5bf92ca28f735a42b120e8229cc8ff1bdb23676",
    (
        "trigger",
        "trg_grant_ledger_incoming_update",
        "economy_ledger_transactions",
    ): "145d5b521c46181f6e9eff290bd5d64899964d996d48421233ed94485ea1ba25",
    (
        "table",
        "safety_capabilities",
        "safety_capabilities",
    ): "06097ce80a177dcec133322e82bd386337a591a8cbe1a5e5b5237438243a6b5f",
    (
        "table",
        "economy_corrections",
        "economy_corrections",
    ): "7ca64102ae64035c7c6b25fbc11284c6dcf4388ab9bc60f612513be69d95f8a6",
    (
        "index",
        "ix_correction_actor_time",
        "economy_corrections",
    ): "5f2d8ec12c0e81dd349401d3fdd733f3fbea9f12d0a458268d53417dc38cba8d",
    (
        "trigger",
        "trg_correction_update",
        "economy_corrections",
    ): "8418e67ab191eb0d520cb6e41aa799aff6e8fdfa6ba218165a65f903abf6e7b4",
    (
        "trigger",
        "trg_correction_delete",
        "economy_corrections",
    ): "be7ab2ca7765f791c0c3c7aae08dae7e6cb9db27ca0347097e80c77e07c5fc3d",
    (
        "trigger",
        "trg_correction_replace",
        "economy_corrections",
    ): "0368e19d07ece0a9d6bf74bfbfd671a2bc2b1b2e7044bc02043e5ab15cefd625",
    (
        "trigger",
        "trg_correction_postings_update",
        "economy_ledger_postings",
    ): "6b0addc55a72d16efcd53d2c89a6d106fe828601fb259e17cb7d403ef3ae99e3",
    (
        "trigger",
        "trg_correction_ledger_update",
        "economy_ledger_transactions",
    ): "751b8067fcef5968d2ea54eb6c862b117201a0fdf0dcc8cda86ee3b86915c5ad",
    (
        "trigger",
        "trg_correction_postings_delete",
        "economy_ledger_postings",
    ): "0ed9b29483bde1b3cfdc07c4a1a2b7259d6d280c25c30c3599dd1980bba6f8e6",
    (
        "trigger",
        "trg_correction_ledger_delete",
        "economy_ledger_transactions",
    ): "9b08c701c9610eb46555152fa310cac2a9aa1118d0252511620d701536f52d94",
    (
        "trigger",
        "trg_correction_postings_insert",
        "economy_ledger_postings",
    ): "fb13b02d556465b34f0d8b9170e5638f6808a974cb142f2c4374393008a7c908",
    (
        "trigger",
        "trg_correction_ledger_insert",
        "economy_ledger_transactions",
    ): "0401742b5afba6246c91bfc91dbbe853c884c1431e7aa1759603107316f8a1b4",
    (
        "trigger",
        "trg_correction_validate",
        "economy_corrections",
    ): "7834833a53c76f7b1f7e45f81298068d2b851ce49e9695b636014d8f58531a83",
}
