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
    name="veo",
    description="Generate videos using Google's Veo 3.1 Fast model",
)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="Text to Video", value="text-to-video"),
        app_commands.Choice(name="Image to Video", value="image-to-video"),
        app_commands.Choice(name="First & Last Frame to Video", value="first-last-frame"),
    ],
    aspect_ratio=[
        app_commands.Choice(name="Landscape 16:9", value="16:9"),
        app_commands.Choice(name="Portrait 9:16", value="9:16"),
        app_commands.Choice(name="Square 1:1", value="1:1"),
    ],
)
async def command(
    interaction: discord.Interaction,
    mode: Literal["text-to-video", "image-to-video", "first-last-frame"],  # Required, first
    prompt: str,  # Required, second
    aspect_ratio: str = "16:9",  # Optional, defaults to 16:9
    start_frame: discord.Attachment | None = None,  # Used for both i2v and first-last-frame
    last_frame: discord.Attachment | None = None,  # Only for first-last-frame mode
):
    user_id = interaction.user.id

    # Try to acquire rate limit slot
    if not await rate_limiter.acquire(user_id, model="veo"):
        stats = rate_limiter.get_stats(user_id, model="veo")
        can_generate, reason = rate_limiter.can_generate(user_id, model="veo")
        
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

    try:
        # Validate mode-specific requirements
        if mode == "image-to-video" and start_frame is None:
            embed = discord.Embed(
                title="❌ Start Frame Required",
                description="Please upload a start_frame for image-to-video mode.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if mode == "first-last-frame" and (start_frame is None or last_frame is None):
            embed = discord.Embed(
                title="❌ Frames Required",
                description="Please upload both `start_frame` and `last_frame` for first-last-frame mode.",
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

        # Moderate start_frame if provided
        if start_frame:
            frame_safe, frame_reason = await moderation.moderate_image(start_frame.url, prompt)
            if not frame_safe:
                embed = discord.Embed(
                    title="🚫 Content Moderation Failed",
                    description=f"Your start frame was flagged: {frame_reason}",
                    color=discord.Color.red(),
                )
                await interaction.edit_original_response(content=None, embed=embed)
                return

        # Moderate last_frame if provided
        if last_frame:
            frame_safe, frame_reason = await moderation.moderate_image(last_frame.url, prompt)
            if not frame_safe:
                embed = discord.Embed(
                    title="🚫 Content Moderation Failed",
                    description=f"Your last frame was flagged: {frame_reason}",
                    color=discord.Color.red(),
                )
                await interaction.edit_original_response(content=None, embed=embed)
                return

        # Update status
        await interaction.edit_original_response(content="🎬 Generating video with Veo 3.1...")

        # Create aspect ratio display name
        aspect_ratio_map = {
            "16:9": "Landscape 16:9",
            "9:16": "Portrait 9:16",
            "1:1": "Square 1:1",
        }
        aspect_ratio_display = aspect_ratio_map.get(aspect_ratio, aspect_ratio)

        # Prepare request based on mode
        if mode == "text-to-video":
            api_endpoint = "fal-ai/veo3.1/fast"
            request_data = {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
            }
        elif mode == "image-to-video":
            api_endpoint = "fal-ai/veo3.1/fast/image-to-video"
            request_data = {
                "prompt": prompt,
                "image_url": start_frame.url,
                "aspect_ratio": aspect_ratio,
            }
        else:  # first-last-frame
            api_endpoint = "fal-ai/veo3.1/fast/first-last-frame-to-video"
            request_data = {
                "prompt": prompt,
                "first_frame_url": start_frame.url,
                "last_frame_url": last_frame.url,
                "aspect_ratio": aspect_ratio,
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

            # Check file size (Discord limit is 25MB for non-nitro)
            file_size_mb = len(video_data) / (1024 * 1024)

            # Create mode display name
            mode_display = {
                "text-to-video": "Text to Video",
                "image-to-video": "Image to Video",
                "first-last-frame": "First & Last Frame to Video",
            }.get(mode, mode)

            if file_size_mb > 25:
                # File too large, send link instead
                embed = discord.Embed(
                    title="🎬 Veo 3.1 Generated Video",
                    description=f"Video is too large to attach. [Click here to view]({video_url}).",
                    color=0x7289DA,
                )

                embed.add_field(
                    name="Prompt",
                    value=prompt[:1024] if len(prompt) <= 1024 else prompt[:1021] + "...",
                    inline=False,
                )

                embed.add_field(name="Mode", value=mode_display, inline=True)
                embed.add_field(name="Aspect Ratio", value=aspect_ratio_display, inline=True)

                stats = rate_limiter.get_stats(user_id, model="veo")
                embed.add_field(
                    name="Usage",
                    value=f"{stats['remaining']}/{stats['daily_limit']} remaining",
                    inline=True,
                )

                embed.add_field(
                    name="Generated by",
                    value=f"{interaction.user.mention}",
                    inline=False,
                )

                await interaction.edit_original_response(content=None, embed=embed)
            else:
                # Create file from video data
                video_file = discord.File(
                    io.BytesIO(video_data), filename="veo_video.mp4"
                )

                # Create beautiful embed with video info
                embed = discord.Embed(
                    title="🎬 Veo 3.1 Generated Video",
                    description=f"For full resolution, [click here]({video_url}).",
                    color=0x7289DA,
                )

                embed.add_field(
                    name="Prompt",
                    value=prompt[:1024] if len(prompt) <= 1024 else prompt[:1021] + "...",
                    inline=False,
                )

                embed.add_field(name="Mode", value=mode_display, inline=True)
                embed.add_field(name="Aspect Ratio", value=aspect_ratio_display, inline=True)

                stats = rate_limiter.get_stats(user_id, model="veo")
                embed.add_field(
                    name="Usage",
                    value=f"{stats['remaining']}/{stats['daily_limit']} remaining",
                    inline=True,
                )

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
            # If download fails, send link instead
            embed = discord.Embed(
                title="🎬 Veo 3.1 Generated Video",
                description=f"[Click here to view your video]({video_url}).\n\n"
                f"⚠️ Could not download video automatically.",
                color=0x7289DA,
            )

            embed.add_field(
                name="Prompt",
                value=prompt[:1024] if len(prompt) <= 1024 else prompt[:1021] + "...",
                inline=False,
            )

            mode_display = {
                "text-to-video": "Text to Video",
                "image-to-video": "Image to Video",
                "first-last-frame": "First & Last Frame to Video",
            }.get(mode, mode)

            embed.add_field(name="Mode", value=mode_display, inline=True)
            embed.add_field(name="Aspect Ratio", value=aspect_ratio_display, inline=True)

            stats = rate_limiter.get_stats(user_id, model="veo")
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