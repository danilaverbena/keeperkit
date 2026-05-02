from keeperkit import Network, WorkflowBuilder


def test_builder_chains_edges():
    wf = (
        WorkflowBuilder("chain test")
        .manual_trigger()
        .action("balance", "web3/check-balance",
                network=Network.BASE_SEPOLIA,
                address="0xdeadbeef0000000000000000000000000000beef")
        .action("read", "web3/read-contract",
                network="84532",
                contractAddress="0xcafe000000000000000000000000000000000000",
                functionName="totalSupply")
        .build()
    )
    assert wf.name == "chain test"
    assert len(wf.nodes) == 3
    # Edges chain trigger->balance->read.
    assert len(wf.edges) == 2
    assert wf.edges[0].source == wf.nodes[0].id
    assert wf.edges[0].target == wf.nodes[1].id
    assert wf.edges[1].source == wf.nodes[1].id
    assert wf.edges[1].target == wf.nodes[2].id


def test_schedule_trigger_carries_cron():
    wf = (
        WorkflowBuilder("hourly")
        .schedule_trigger("0 * * * *")
        .action("balance", "web3/check-balance",
                network=Network.SEPOLIA,
                address="0x0000000000000000000000000000000000000000")
        .build()
    )
    trigger = wf.nodes[0]
    assert trigger.type == "trigger"
    assert trigger.data.config["cron"] == "0 * * * *"
    assert trigger.data.config["triggerType"] == "Schedule"


def test_explicit_after_anchors_branch():
    wf = (
        WorkflowBuilder("branch")
        .manual_trigger()
        .action("a", "web3/check-balance",
                network=Network.SEPOLIA,
                address="0x0000000000000000000000000000000000000000")
    )
    a_id = wf._last_id  # noqa: SLF001 - testing internal anchor
    wf.action("b", "web3/check-balance", network=Network.SEPOLIA,
              address="0x0000000000000000000000000000000000000000")
    wf.action("c", "web3/check-balance", network=Network.SEPOLIA,
              address="0x0000000000000000000000000000000000000000",
              after=a_id)
    built = wf.build()
    sources = [edge.source for edge in built.edges]
    assert sources.count(a_id) == 2  # b and c both branch off a
