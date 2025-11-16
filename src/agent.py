import logging
from datetime import datetime
from dotenv import load_dotenv
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics,
    get_job_context,
    ChatContext,
    CloseEvent,
    
)
from livekit import rtc, api
from livekit.agents.llm import function_tool
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
import os
from livekit.agents.llm import ToolError
from dataclasses import dataclass
import asyncio
from livekit.agents import AgentTask, function_tool
import requests
import logging
import aiohttp
import asyncio
import json
from dataclasses import  asdict
from datetime import datetime
from zoneinfo import ZoneInfo
from livekit import api
from livekit.protocol.sip import SIPCallInfo


logger = logging.getLogger("main")

load_dotenv("/home/raymond/Projects/LeadOutbountCaller/.env.local")
outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")



def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


@dataclass
class UserData:
    is_availale: bool = None
    date: str = None
    time: str = None


@dataclass
class MetaData:
    call_id: str = None
    created_at: str  = None
    ended_at: str = None
    duration_seconds: float = None
    called_number: str = None
    disconnection_reason: str = None


async def hangup_call():
    ctx = get_job_context()
    if ctx is None:
        # Not running in a job context
        return
    
    await ctx.api.room.delete_room(
        api.DeleteRoomRequest(
            room=ctx.room.name,
        )
    )




    
class Assistant(Agent):
    def __init__(self):
        instuctions = f"""
        la data et l'heure actuel: {datetime.now().isoformat()}
        Tu es la voix officielle de Voix-Up, une agence spécialisée dans la création, l’intégration et le déploiement de call-bots professionnels et sur mesure pour les entreprises.

        Ta mission est d’expliquer clairement et simplement ce que fait Voix-Up, en mettant en avant :
        - la conception de callbots personnalisés adaptés aux besoins de chaque entreprise,
        - l’automatisation des appels entrants et sortants,
        - l'amélioration de l’efficacité des équipes,
        - la réduction des coûts opérationnels,
        - l’intégration fluide avec les outils et systèmes existants (CRM, téléphonie, bases de données, etc.),
        - la possibilité de créer des scénarios vocaux intelligents : prise de rendez-vous, réponses automatiques, qualification d’appels, support client, gestion de demandes, etc.

        Ton rôle :
        - présenter VoixUp de manière professionnelle, chaleureuse et rassurante,
        - expliquer la valeur ajoutée de nos callbots,
        - mettre en avant notre approche personnalisée et orientée résultat,
        - répondre clairement aux questions sur nos services,
        - orienter la conversation vers une démonstration ou un échange avec un expert VoixUp si nécessaire.

        Règles :
        1. Toujours parler au nom de VoixUp en utilisant “nous”.
        2. Être précis, professionnel et accessible.
        3. Ne jamais inventer de fonctionnalités fictives : uniquement rester dans les services décrits.
        4. Ne jamais sortir de ton rôle de représentante officielle de VoixUp.
        5. Ton ton doit être : professionnel, moderne, confiant et convivial.

        Tu es prête à présenter VoixUp et à expliquer notre expertise en callbots personnalisés.
        """
        super().__init__(instructions=instuctions)

    async def on_enter(self) -> None:
        await self.session.say(
            text="Bonjour, c’est Linda de Voix-Up. Merci pour votre intérêt ! J’aimerais comprendre vos besoins pour voir comment notre solution peut vous aider. Est-ce que vous avez une minute ?")      
    
    @function_tool
    async def end_call(self, ctx: RunContext):
        """Called when the user wants to end the call"""
        await ctx.wait_for_playout() # let the agent finish speaking
        await hangup_call()

    @function_tool
    async def detected_answering_machine(self):
        """Call this tool if you have detected a voicemail system, AFTER hearing the voicemail greeting"""
        await self.session.generate_reply(
            instructions="Leave a voicemail message letting the user know you'll call back later."
        )
        await asyncio.sleep(0.5) # Add a natural gap to the end of the voicemail message
        await hangup_call()


            

async def entrypoint(ctx: JobContext):

    await ctx.connect()

    userdata = UserData()
    metadata = MetaData()

    logger.info(f"connecting to room '{ctx.room.name}'") # room : "my-room"
    logger.info(f"room metadata : '{ctx.job.metadata}'") # room metadata : 'hello from dispatch'

    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    # Set up a voice AI pipeline using OpenAI, Cartesia, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        stt=deepgram.STT(language="fr",model="nova-2"),  # Use `language="fr-FR"` for French
        llm=openai.LLM(model="gpt-4.1-mini-2025-04-14"),
        tts=cartesia.TTS(voice="65b25c5d-ff07-4687-a04c-da2f43ef6fa9",model="sonic-2",language="fr"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
        userdata = userdata
    )

    @session.on("close")
    def on_close(ev: CloseEvent):

        logger.info(f"Type of disconnection: {ev.reason}")
        #logger.info(f"List of participants: {ctx.api.room.list_participants(api.ListParticipantsRequest(room=ctx.room.name))}")
        logger.info(f"Agent disconnect reason {ctx.agent.disconnect_reason}")

        
        
        started_at = ctx.room.creation_time.astimezone(tz=ZoneInfo("Europe/Paris"))
        ended_at = datetime.fromtimestamp(ev.created_at, tz=ZoneInfo("Europe/Paris"))

        # Log with formatted strings
        logger.info(f"Call started at: {started_at.isoformat()}")
        logger.info(f"Call ended at: {ended_at.isoformat()}")

        # Calculate duration
        duration = ended_at - started_at
        duration_seconds = duration.total_seconds()

        # Metadata
        metadata.disconnection_reason = ev.reason.name
        metadata.created_at = started_at.isoformat()
        metadata.ended_at = ended_at.isoformat()
        metadata.duration_seconds = duration_seconds

        logger.info(f"Metadata dict: {asdict(metadata)}")
        # Send data to backend APi asynchronously        
        async def post_data():
            async with aiohttp.ClientSession() as session:
                
                async with session.post("http://0.0.0.0:8000/calls", json=asdict(metadata)) as response:
                    return await response.json()
                
        # If you need the result, use ensure_future with callback
        task = asyncio.create_task(post_data())
        task.add_done_callback(lambda t: logger.info(f"Result from API: {t.result()}"))

    await session.start(
            agent=Assistant(),
            room=ctx.room,
            room_input_options=RoomInputOptions(
                # enable Krisp background voice and noise removal
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
        
    # Handler for participant connection  
    def on_participant_connected_handler(participant: rtc.RemoteParticipant):  
        asyncio.create_task(async_on_participant_connected(participant))  
    
    # Handler for attribute changes (call status)  
    def on_participant_attributes_changed_handler(changed_attributes: dict, participant: rtc.Participant):  
        asyncio.create_task(async_on_participant_attributes_changed(changed_attributes, participant))  
    
    async def async_on_participant_connected(participant: rtc.RemoteParticipant):  
        logger.info(f"Participant connected: {participant.identity}")

        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:  
            logger.info(f"AGENT participant connected: {participant.identity}")  
        
        # Check if this is a SIP participant  
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:  
            logger.info(f"SIP participant connected: {participant.identity}")  
            
            # Log initial SIP attributes  
            if participant.attributes:  
                call_status = participant.attributes.get('sip.callStatus', 'Unknown')  
                phone_number = participant.attributes.get('sip.phoneNumber', 'Unknown')  
                logger.info(f"Initial call status: {call_status}")  
                logger.info(f"Phone number: {phone_number}")  
    
    async def async_on_participant_attributes_changed(changed_attributes: dict, participant: rtc.Participant):  
            logger.info(f"Participant {participant.identity} attributes changed: {changed_attributes}")  


            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
                logger.info(f"Participant kind: {rtc.ParticipantKind.PARTICIPANT_KIND_AGENT}")
            
            # Check if this is a SIP participant and if call status has changed  
            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:  
                logger.info(f"Participant kind: {rtc.ParticipantKind.PARTICIPANT_KIND_SIP}")
                
                if 'sip.callStatus' in changed_attributes:  
                    call_status = changed_attributes['sip.callStatus']  
                    logger.info(f"SIP Call Status updated: {call_status}")  
                    
                    # Handle different call statuses  
                    if call_status == 'ringing':  
                        logger.info("Inbound call is ringing for the caller")  
                    elif call_status == 'active':  
                        logger.info("Call is now active and connected")  
                    elif call_status == 'dialing':  
                        logger.info("Call is dialing and waiting to be picked up")  
                    elif call_status == 'automation':  
                        logger.info("Call is connected and dialing DTMF numbers")  
                    elif call_status == 'hangup':  
                        logger.info("Call has been ended by a participant")  
    
    # Register both event handlers  
    ctx.room.on("participant_connected", on_participant_connected_handler)  
    ctx.room.on("participant_attributes_changed", on_participant_attributes_changed_handler)

        # wait for the agent session start and participant join
        #participant = await ctx.wait_for_participant()
        #logger.info(f"participant joined: {participant.identity}")



    



if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint,
                              agent_name="demo-outbound-agent",
                              prewarm_fnc=prewarm,
                              initialize_process_timeout=60
                            ))
    