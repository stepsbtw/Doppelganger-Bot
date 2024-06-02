import discord
from discord import app_commands
from discord.ext import listening

from typing import Optional,Literal
from dotenv import load_dotenv
import os
import subprocess

class Client(discord.Client):
    GUILD = discord.Object(id=825134290063982653)

    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Copia os comandos para o server
        self.tree.copy_global_to(guild=self.GUILD)
        await self.tree.sync(guild=self.GUILD)

intents = discord.Intents.default()
client = Client(intents=intents)

# pool pro processamento de audio
process_pool = listening.AudioProcessPool(1)

# mapeia um formato de arquivo para um objeto SINK
FILE_FORMATS = {"mp3": listening.MP3AudioFile, "wav": listening.WaveAudioFile}

async def is_in_guild(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Este comando só pode ser usado em um server.")
        return False
    return True

async def get_vc(interaction: discord.Interaction) -> Optional[listening.VoiceClient]:
    # buscar e conectar ao chat de voz do usuario
    if interaction.guild.voice_client is not None:
        if interaction.guild.voice_client.channel != interaction.user.voice.channel:
            await interaction.guild.voice_client.move_to(interaction.user.voice.channel)
        return interaction.guild.voice_client
    if interaction.user.voice is not None:
        return await interaction.user.voice.channel.connect(cls=listening.VoiceClient)

async def send_audio_file(channel: discord.TextChannel, file: listening.AudioFile):
    user = file.user if file.user is None else file.user.id
    try:
        await channel.send(
            f"Arquivo de voz de <@{user}>" if user is not None else "Não foi possível ligar esse arquivo a um usuário.",
            file=discord.File(file.path),
        )
    except ValueError:
        await channel.send(
            f"Arquivo de voz de <@{user}> é grande demais para enviar."
            if user is not None
            else "Arquivo de voz de [usuário desconhecido] grande demais para enviar"
        )


# The key word arguments passed in the listen function MUST have the same name.
# You could alternatively do on_listen_finish(sink, exc, channel, ...) because exc is always passed
# regardless of if it's None or not.
async def on_listen_finish(sink: listening.AudioFileSink(file_type=listening.MP3AudioFile,output_dir="audio-output"), exc=None, channel=None):
    # Convert the raw recorded audio to its chosen file type
    # kwargs can be specified to convert_files, which will be specified to each AudioFile.convert call
    # here, the stdout and stderr kwargs go to asyncio.create_subprocess_exec for ffmpeg
    try:
        await sink.convert_files(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        print(f"Error occurred during audio conversion: {e}")
    if channel is not None:
        for file in sink.output_files.values():
            await send_audio_file(channel, file)

    # Raise any exceptions that may have occurred
    if exc is not None:
        raise exc

@client.event
async def on_ready():
    print(f'Logado como {client.user} (ID: {client.user.id})')
    print('------')


@client.tree.command(description="Conecta-se ao chat de voz que você está e começa a gravação.")
@app_commands.describe(
    file_format=f"O formato do arquivo o qual será feita a gravação. Tipos válidos: {', '.join(FILE_FORMATS.keys())}"
)
async def start(interaction: discord.Interaction, file_format: Literal["mp3", "wav"] = "mp3"):
    if not await is_in_guild(interaction):
        return
    # Checar se o formato inserido é válido.
    file_format = file_format.lower()
    if file_format not in FILE_FORMATS:
        return await interaction.response.send_message(
            "Não é um formato válido. " f"Formatos de arquivo válidos: {', '.join(FILE_FORMATS.keys())}"
        )
    vc = await get_vc(interaction)
    if vc is None:
        return await interaction.response.send_message("Usuário não está em um chat de voz.")
    if vc.is_listen_receiving():
        return await interaction.response.send_message("Algo já está sendo gravado.")
    if vc.is_listen_cleaning():
        return await interaction.response.send_message("Limpeza em andamento... Aguarde um instante.")

    # Start listening for audio and pass it to one of the AudioFileSink objects which will
    # record the audio to file for us. We're also passing the on_listen_finish function
    # which will be called when listening has finished.
    vc.listen(
        listening.AudioFileSink(FILE_FORMATS[file_format], "audio-output"),
        process_pool,
        after=on_listen_finish,
        channel=interaction.channel
    )
    await interaction.response.send_message("Gravação iniciada.")


@client.tree.command(description="Para a gravação atual.")
async def stop(interaction: discord.Interaction):
    if not await is_in_guild(interaction):
        return
    if interaction.guild.voice_client is None or not (await get_vc(interaction)).is_listen_receiving():
        return await interaction.response.send_message("Não há nada sendo gravado no momento.")
    vc = interaction.guild.voice_client
    vc.stop_listening()
    await interaction.response.send_message("Gravação parada. Arquivos serão enviados assim que o processamento terminar.")
    await vc.disconnect()

if __name__ == "__main__": # importante pro multiprocessamento
    load_dotenv()
    try:
        client.run(os.getenv("DISCORD_TOKEN"))
    finally:
        process_pool.cleanup_processes()