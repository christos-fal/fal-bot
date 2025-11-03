import io
from typing import Literal

import discord
import fal_client
import httpx
from discord import app_commands

from fal_bot import config, moderation
from fal_bot.rate_limiter import rate_limiter

# Configure fal_client with your API key
fal_client.api_key = config.FAL_SECRET


@app_commands.command(
    name="ovi",
    description="Generate a video using Ovi text-to-video or image-to-video model",
)
async def command(
    interaction: discord.Interaction,
    mode: Literal["text-to-video", "image-to-video"],
    prompt: str,
    image: discord.Attachment | None = None,
):
    user_id = interaction.user.id

    # Check rate limits
    can_generate, reason = rate_limiter.can_generate(user_id)
    if not can_generate:
        stats = rate_limiter.get_stats(user_id)
        embed = discord.Embed(
            title="⏱️ Rate Limit Reached",
            description=reason,
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="Your Usage",
            value=f"**{stats['used']}/{stats['daily_limit']}** generations used today\n"
            f"**{stats['remaining']}** remaining",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Acquire rate limit slot
    if not await rate_limiter.acquire(user_id):
        await interaction.response.send_message(
            "❌ Failed to acquire generation slot. Please try again.", ephemeral=True
        )
        return

    try:
        # Validate image requirement for image-to-video mode
        if mode == "image-to-video" and image is None:
            embed = discord.Embed(
                title="❌ Image Required",
                description="Please upload an image for image-to-video mode.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Send initial response
        await interaction.response.send_message("🔍 Checking content safety...")

        # Moderate text prompt
        text_safe, text_reason = await moderation.moderate_text(prompt)
        if not text_safe:
            embed = discord.Embed(
                title="🚫 Content Moderation Failed",
                description=f"Your prompt was flagged: {text_reason}",
                color=discord.Color.red(),
            )
            await interaction.edit_original_response(content=None, embed=embed)
            return

        # Moderate image if provided
        if image:
            # Moderate image using Discord's CDN URL directly
            image_safe, image_reason = await moderation.moderate_image(
                image.url, prompt
            )
            if not image_safe:
                embed = discord.Embed(
                    title="🚫 Content Moderation Failed",
                    description=f"Your image was flagged: {image_reason}",
                    color=discord.Color.red(),
                )
                await interaction.edit_original_response(content=None, embed=embed)
                return

        # Update status
        await interaction.edit_original_response(content="🎬 Generating video...")

        # Prepare request based on mode
        if mode == "text-to-video":
            api_endpoint = "fal-ai/ovi"
            request_data = {
                "prompt": prompt,
            }
        else:  # image-to-video
            api_endpoint = "fal-ai/ovi/image-to-video"
            request_data = {
                "prompt": prompt,
                "image_url": image.url,
            }

        # Submit to fal.ai
        result = await fal_client.run_async(api_endpoint, arguments=request_data)

        # Get video URL
        video_url = result.get("video", {}).get("url")

        if not video_url:
            await interaction.edit_original_response(
                content="❌ Failed to generate video. No video URL returned."
            )
            return

        # Download and send the video
        try:
            await interaction.edit_original_response(content="📥 Downloading video...")

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(video_url)
                response.raise_for_status()
                video_data = response.content

            # Check file size (Discord limit is 25MB for non-nitro, 500MB for nitro)
            file_size_mb = len(video_data) / (1024 * 1024)

            # Get generation metadata from result
            seed = result.get("seed", "N/A")

            if file_size_mb > 25:
                # File too large, send link instead
                embed = discord.Embed(
                    title="🎬 Ovi Generated Video",
                    description=f"For the full resolution video, click [here]({video_url}).",
                    color=0x7289DA,  # Discord blurple color
                )

                # Prompt section
                embed.add_field(
                    name="Prompt",
                    value=prompt[:1024]
                    if len(prompt) <= 1024
                    else prompt[:1021] + "...",
                    inline=False,
                )

                # First row of info
                embed.add_field(
                    name="Mode", value=mode.replace("-", " ").title(), inline=True
                )
                embed.add_field(
                    name="Resolution", value="992x512", inline=True
                )  # Or get from result
                embed.add_field(
                    name="Inference Steps", value="30", inline=True
                )  # Or get from result

                # Second row of info
                embed.add_field(name="Seed", value=str(seed), inline=True)

                # Usage stats
                stats = rate_limiter.get_stats(user_id)
                embed.add_field(
                    name="Usage",
                    value=f"{stats['remaining']}/{stats['daily_limit']} remaining",
                    inline=True,
                )

                # Generated by
                embed.add_field(
                    name="Generated by",
                    value=f"{interaction.user.mention}",
                    inline=False,
                )

                await interaction.edit_original_response(content=None, embed=embed)
            else:
                # Create file from video data
                video_file = discord.File(
                    io.BytesIO(video_data), filename="ovi_video.mp4"
                )

                # Create beautiful embed with video info
                embed = discord.Embed(
                    title="Ovi Generated Video",
                    description=f"For the full resolution video, click [here]({video_url}).",
                    color=0x7289DA,  # Discord blurple color
                )

                # Prompt section
                embed.add_field(
                    name="Prompt",
                    value=prompt[:1024]
                    if len(prompt) <= 1024
                    else prompt[:1021] + "...",
                    inline=False,
                )

                # First row of info
                embed.add_field(
                    name="Mode", value=mode.replace("-", " ").title(), inline=True
                )
                embed.add_field(
                    name="Resolution", value="992x512", inline=True
                )  # Adjust based on mode
                embed.add_field(name="Inference Steps", value="30", inline=True)

                # Second row of info
                embed.add_field(name="Seed", value=str(seed), inline=True)

                # Usage stats
                stats = rate_limiter.get_stats(user_id)
                embed.add_field(
                    name="Usage",
                    value=f"{stats['remaining']}/{stats['daily_limit']} remaining",
                    inline=True,
                )

                # Generated by
                embed.add_field(
                    name="Generated by",
                    value=f"{interaction.user.mention}",
                    inline=False,
                )

                # Send video as attachment with embed
                await interaction.edit_original_response(
                    content=None, embed=embed, attachments=[video_file]
                )

        except httpx.HTTPError:
            # If download fails, send link instead with same beautiful format
            embed = discord.Embed(
                title="Ovi Generated Video",
                description=f"For the full resolution video, click [here]({video_url}).\n\n"
                f"⚠️ Could not download video automatically.",
                color=0x7289DA,
            )

            embed.add_field(
                name="Prompt",
                value=prompt[:1024] if len(prompt) <= 1024 else prompt[:1021] + "...",
                inline=False,
            )

            embed.add_field(
                name="Mode", value=mode.replace("-", " ").title(), inline=True
            )

            stats = rate_limiter.get_stats(user_id)
            embed.add_field(
                name="Usage",
                value=f"{stats['remaining']}/{stats['daily_limit']} remaining",
                inline=True,
            )

            embed.add_field(
                name="Generated by", value=f"{interaction.user.mention}", inline=False
            )

            await interaction.edit_original_response(content=None, embed=embed)

    except Exception as e:
        error_message = str(e)
        embed = discord.Embed(
            title="❌ Error",
            description=f"Failed to generate video: {error_message}",
            color=discord.Color.red(),
        )

        try:
            await interaction.edit_original_response(content=None, embed=embed)
        except Exception:
            await interaction.followup.send(embed=embed, ephemeral=True)

    finally:
        # Always release the rate limit slot
        rate_limiter.release(user_id)
