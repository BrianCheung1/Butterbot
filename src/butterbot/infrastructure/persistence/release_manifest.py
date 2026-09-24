"""Frozen case-sensitive schema fingerprints for release 20260922_0004."""

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
        "safety_capabilities",
        "safety_capabilities",
    ): "c3e6118fc4f8a73202348c824c383746117b36dea210771a7738a02c5108dfc1",
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
}
