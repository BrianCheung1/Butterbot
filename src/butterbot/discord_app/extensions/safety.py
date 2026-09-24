import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Protocol, cast
from uuid import UUID

import discord
from discord import app_commands
from discord.ext import commands

from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.application.operations.telemetry import emit_operational_telemetry
from butterbot.application.safety.ports import Capability, Operation
from butterbot.application.safety.service import (
    InspectionResult,
    ProposalView,
    SafetyResult,
    SafetyService,
)

logger = logging.getLogger(__name__)


class Safety(commands.Cog):
    def __init__(self, service: SafetyService, telemetry: OperationsTelemetry) -> None:
        self._service = service
        self._telemetry = telemetry

    async def _respond(
        self,
        interaction: discord.Interaction,
        command: str,
        execute: Callable[[], Awaitable[SafetyResult | InspectionResult | ProposalView]],
    ) -> None:
        started = perf_counter()
        outcome = "failed"
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await execute()
                outcome = result.status
                if isinstance(result, ProposalView):
                    proposal = result.proposal
                    message = f"Proposal inspection: {result.status}."
                    if proposal is not None:
                        target_text = (
                            "global"
                            if proposal.targets == (0,)
                            else ", ".join(str(target) for target in proposal.targets)
                        )
                        message = (
                            f"Proposal: {proposal.id}\nStatus: {proposal.status}\n"
                            f"Scope verified: {proposal.scope_verified}\n"
                            f"Proposer: {proposal.actor_id}\nOperation: {proposal.operation}\n"
                            f"Targets: {target_text}\nCoins per target: {proposal.amount:,}\n"
                            f"Total coins: {proposal.amount * len(proposal.targets):,}\n"
                            f"Second approval required: {proposal.requires_approval}\n"
                            f"Expires: <t:{proposal.expires_at_ms // 1000}:f>\n"
                            f"Reason: {discord.utils.escape_markdown(proposal.reason)}"
                            + (
                                ""
                                if proposal.scope_verified
                                else "\nLegacy/unverified scope: submit a new proposal."
                            )
                        )
                elif isinstance(result, InspectionResult):
                    message = (
                        f"Inspection: {result.status}. "
                        f"Full freeze: {'yes' if result.frozen else 'no'}."
                    )
                    if result.status == "available" and result.amount is not None:
                        message += f" Wallet: {result.amount:,} coins."
                else:
                    message = f"Administrative request: {result.status}."
                    if result.proposal_id is not None:
                        message += f" Proposal: {result.proposal_id}."
                    if result.status == "approved":
                        message += " No coins issued; grant execution is not implemented."
            except (ValueError, TypeError):
                outcome = "invalid"
                message = "Invalid input. Use valid IDs, a supported operation, and a short reason."
            except Exception as error:
                logger.error("Administrative command failed with %s", type(error).__name__)
                message = "Could not complete this administrative request. Please try again later."
            await interaction.followup.send(
                message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        except BaseException:
            outcome = "failed"
            raise
        finally:
            emit_operational_telemetry(
                "discord.command_completed",
                lambda: self._telemetry.discord_command_completed(
                    command=command, outcome=outcome, duration_ms=(perf_counter() - started) * 1000
                ),
            )

    @app_commands.command(
        name="admin_inspect",
        description="Privately inspect a player with audited durable authorization.",
    )
    async def inspect(
        self, interaction: discord.Interaction, user: discord.User, reason: str
    ) -> None:
        await self._respond(
            interaction,
            "admin_inspect",
            lambda: self._service.inspect(
                actor_id=interaction.user.id, target_id=user.id, reason=reason
            ),
        )

    @app_commands.command(
        name="admin_capability", description="Grant or revoke a durable administrator capability."
    )
    async def capability(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        capability: Capability,
        enabled: bool,
        reason: str,
    ) -> None:
        await self._respond(
            interaction,
            "admin_capability",
            lambda: self._service.change_capability(
                actor_id=interaction.user.id,
                target_id=user.id,
                capability=capability,
                enabled=enabled,
                reason=reason,
                interaction_id=interaction.id,
            ),
        )

    @app_commands.command(
        name="admin_propose", description="Propose a freeze, release, or non-executing grant."
    )
    @app_commands.describe(
        targets="Comma-separated Discord user IDs (max 25), or global for full freeze/release",
        amount="Coins per target for a grant proposal; zero for freeze/release",
    )
    async def propose(
        self,
        interaction: discord.Interaction,
        operation: Operation,
        targets: str,
        reason: str,
        amount: str = "0",
    ) -> None:
        async def execute() -> SafetyResult:
            parts = targets.split(",")
            if len(targets) > 500 or len(parts) > 25:
                raise ValueError("too many targets")
            if targets == "global":
                ids = (0,)
            else:
                if any(not part.isascii() or not part.isdecimal() for part in parts):
                    raise ValueError("invalid targets")
                ids = tuple(int(part) for part in parts)
            if len(amount) > 19 or not amount.isascii() or not amount.isdecimal():
                raise ValueError("invalid amount")
            return await self._service.propose(
                actor_id=interaction.user.id,
                operation=operation,
                targets=ids,
                amount=int(amount),
                reason=reason,
                interaction_id=interaction.id,
            )

        await self._respond(interaction, "admin_propose", execute)

    @app_commands.command(
        name="admin_proposal",
        description="Privately review an exact stored proposal before approval.",
    )
    async def proposal(self, interaction: discord.Interaction, proposal: str) -> None:
        async def execute() -> ProposalView:
            return await self._service.view_proposal(
                actor_id=interaction.user.id, proposal_id=UUID(proposal)
            )

        await self._respond(interaction, "admin_proposal", execute)

    @app_commands.command(
        name="admin_approve",
        description="Approve a pending proposal created by another authorized operator.",
    )
    async def approve(self, interaction: discord.Interaction, proposal: str) -> None:
        async def execute() -> SafetyResult:
            return await self._service.approve(
                actor_id=interaction.user.id,
                proposal_id=UUID(proposal),
                interaction_id=interaction.id,
            )

        await self._respond(interaction, "admin_approve", execute)


class _SafetyBot(Protocol):
    safety_service: SafetyService | None
    operations_telemetry: OperationsTelemetry


async def setup(bot: commands.Bot) -> None:
    dependencies = cast("_SafetyBot", bot)
    if dependencies.safety_service is None:
        raise RuntimeError("safety application service was not composed")
    await bot.add_cog(Safety(dependencies.safety_service, dependencies.operations_telemetry))
