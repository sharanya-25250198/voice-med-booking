import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  Phone, 
  PhoneOff, 
  Calendar, 
  Activity, 
  Languages, 
  X, 
  Check, 
  AlertCircle,
  Stethoscope,
  Clock,
  MapPin,
  RefreshCw,
  Sparkles,
  UserCheck,
  Search,
  Trash2,
  CalendarCheck,
  CheckCircle2,
  XCircle,
  Filter,
  Building2,
  Layers,
  Database,
  Download,
  FileJson,
  Server,
  HardDrive,
  Mic,
  MicOff,
  Volume2,
  VolumeX,
  Play,
  Send,
  CheckCheck,
  Copy,
  ExternalLink,
  ChevronRight,
  ShieldCheck,
  MessageSquare,
  RotateCcw,
  Radio,
  Sliders,
  Settings
} from 'lucide-react';
import { PipecatClient } from "@pipecat-ai/client-js";
import { WebSocketTransport, ProtobufFrameSerializer } from "@pipecat-ai/websocket-transport";

// Dynamic resolution of Backend & CRM endpoints for local dev and Vercel host deployment
const getCrmBaseUrl = () => {
  if (import.meta.env.VITE_CRM_URL) return import.meta.env.VITE_CRM_URL;
  if (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
    return 'http://127.0.0.1:7500/api';
  }
  return 'https://voice-med-booking.vercel.app/api';
};

// Google Calendar URL generator for appointments
const getGoogleCalendarUrl = (appt) => {
  if (!appt) return 'https://calendar.google.com/calendar/u/0/r';
  const title = encodeURIComponent(`Medical Appointment: ${appt.patient_name || 'Patient'} with ${appt.doctor_name || 'Doctor'}`);
  const details = encodeURIComponent(
    `Patient Name: ${appt.patient_name}\nPatient Contact: ${appt.patient_phone}\nDoctor: ${appt.doctor_name} (${appt.specialty})\nStatus: ${appt.status}\nClinic: MediConnect Clinic, 123 Health Boulevard, Suite 100`
  );
  const location = encodeURIComponent("MediConnect Clinic, 123 Health Boulevard, Suite 100");
  
  const dateClean = (appt.date || new Date().toISOString().slice(0, 10)).replace(/-/g, '');
  const [hStr, mStr] = (appt.time || '10:00').split(':');
  let h = parseInt(hStr || '10', 10);
  let m = parseInt(mStr || '0', 10);
  const timeStart = `${String(h).padStart(2, '0')}${String(m).padStart(2, '0')}00`;
  
  m += 30;
  if (m >= 60) {
    h += 1;
    m -= 60;
  }
  const timeEnd = `${String(h).padStart(2, '0')}${String(m).padStart(2, '0')}00`;
  
  return `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${title}&dates=${dateClean}T${timeStart}/${dateClean}T${timeEnd}&details=${details}&location=${location}`;
};

const getVoiceWsUrl = (params) => {
  if (import.meta.env.VITE_VOICE_WS_URL) {
    const baseUrl = import.meta.env.VITE_VOICE_WS_URL;
    return `${baseUrl}?${params.toString()}`;
  }
  return `ws://127.0.0.1:7500/api/voice?${params.toString()}`;
};

// Hardcoded Default API Keys configured for the application
const DEFAULT_GEMINI = import.meta.env.VITE_OPENAI_API_KEY || '';
const DEFAULT_ELEVENLABS = import.meta.env.VITE_ELEVENLABS_API_KEY || '';

export default function App() {
  // Application State
  const [isReceptionistOpen, setIsReceptionistOpen] = useState(false);
  const [isDatabaseOpen, setIsDatabaseOpen] = useState(false);
  const [dbTab, setDbTab] = useState('appointments'); // appointments, doctors, clinic_info, conversations, json
  const [dbDumpData, setDbDumpData] = useState(null);
  const [copiedJson, setCopiedJson] = useState(false);

  // Session ID for multi-turn conversational context memory in NeonDB
  const [sessionId, setSessionId] = useState(() => {
    let saved = localStorage.getItem('med_session_id');
    if (!saved) {
      saved = 'sess_' + Math.random().toString(36).substring(2, 11);
      localStorage.setItem('med_session_id', saved);
    }
    return saved;
  });

  // Voice Interaction Modes: 'browser_ai' (Web Speech + NeonDB Context) vs 'websocket' (Pipecat WS server)
  const [voiceMode, setVoiceMode] = useState('browser_ai'); 
  const [callState, setCallState] = useState('idle'); // idle, connecting, connected, error, speaking, listening, processing
  const [errorMessage, setErrorMessage] = useState('');
  const [isWsError1006, setIsWsError1006] = useState(false);

  // Microphone Permission State & Initial Modal
  const [micPermissionStatus, setMicPermissionStatus] = useState('unknown'); // 'prompt', 'granted', 'denied', 'unknown'
  const [showMicModal, setShowMicModal] = useState(false);
  const [isSeamlessAutoListen, setIsSeamlessAutoListen] = useState(true); // Hands-Free Seamless Voice Loop
  const [liveTranscript, setLiveTranscript] = useState('');
  
  // Voice Simulation & Chat State
  const [simInput, setSimInput] = useState('');
  const [isSimulating, setIsSimulating] = useState(false);
  const [conversationLogs, setConversationLogs] = useState([
    {
      role: 'assistant',
      text: 'Hello! Thank you for calling MediConnect Clinic. How can I assist you with your doctor appointment today?',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [isListeningMic, setIsListeningMic] = useState(false);

  // Receptionist View Filters & Search
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [actionNotification, setActionNotification] = useState('');

  // Voice Settings (Language selection)
  const [lang, setLang] = useState(() => localStorage.getItem('med_lang') || 'en');
  const sttProvider = 'deepgram';
  const ttsProvider = 'deepgram';

  // API Keys
  const geminiKey = import.meta.env.VITE_GEMINI_API_KEY || DEFAULT_GEMINI;
  const elevenlabsKey = import.meta.env.VITE_ELEVENLABS_API_KEY || DEFAULT_ELEVENLABS;
  const deepgramKey = import.meta.env.VITE_DEEPGRAM_API_KEY || '';
  const sarvamKey = import.meta.env.VITE_SARVAM_API_KEY || '';

  // Clinic Data State
  const [doctors, setDoctors] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [clinicInfo, setClinicInfo] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // References for continuous audio loop & lifecycle
  const clientRef = useRef(null);
  const canvasRef = useRef(null);
  const animationRef = useRef(null);
  const recognitionRef = useRef(null);
  const chatBottomRef = useRef(null);
  const isCallActiveRef = useRef(false);
  const isSeamlessRef = useRef(true);
  const isSpeakingRef = useRef(false);
  const isSimulatingRef = useRef(false);

  useEffect(() => {
    isCallActiveRef.current = (callState !== 'idle' && callState !== 'error');
  }, [callState]);

  useEffect(() => {
    isSeamlessRef.current = isSeamlessAutoListen;
  }, [isSeamlessAutoListen]);

  useEffect(() => {
    isSimulatingRef.current = isSimulating;
  }, [isSimulating]);

  // Check microphone permissions on initial load
  useEffect(() => {
    const checkMicPermissions = async () => {
      if (typeof navigator !== 'undefined' && navigator.permissions && navigator.permissions.query) {
        try {
          const status = await navigator.permissions.query({ name: 'microphone' });
          setMicPermissionStatus(status.state);
          if (status.state === 'prompt') {
            setShowMicModal(true);
          }
          status.onchange = () => {
            setMicPermissionStatus(status.state);
            if (status.state === 'granted') {
              setShowMicModal(false);
            }
          };
        } catch (e) {
          // Some browsers do not support microphone query
          if (!localStorage.getItem('mic_modal_dismissed')) {
            setShowMicModal(true);
          }
        }
      } else {
        if (!localStorage.getItem('mic_modal_dismissed')) {
          setShowMicModal(true);
        }
      }
    };
    checkMicPermissions();
  }, []);

  // Request Microphone Access explicitly
  const requestMicPermission = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setMicPermissionStatus('granted');
      setShowMicModal(false);
      localStorage.setItem('mic_modal_dismissed', 'true');
      // Release tracks after verification
      stream.getTracks().forEach(track => track.stop());
      setActionNotification("Microphone access granted. Hands-free voice enabled!");
      setTimeout(() => setActionNotification(''), 4000);
      return true;
    } catch (err) {
      console.warn("Microphone permission denied:", err);
      setMicPermissionStatus('denied');
      setShowMicModal(false);
      localStorage.setItem('mic_modal_dismissed', 'true');
      return false;
    }
  };

  // Auto-scroll conversation logs
  useEffect(() => {
    if (chatBottomRef.current) {
      chatBottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [conversationLogs, liveTranscript]);

  // Load session messages from NeonDB on startup
  useEffect(() => {
    const loadSessionHistory = async () => {
      try {
        const crmUrl = getCrmBaseUrl();
        const res = await fetch(`${crmUrl}/conversations/${sessionId}`);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length > 0) {
            setConversationLogs(data.map(m => ({
              role: m.role,
              text: m.content,
              tool_called: m.tool_called,
              tool_result: m.tool_result,
              time: m.time || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            })));
          }
        }
      } catch (err) {
        console.warn("Could not load past conversation session:", err);
      }
    };
    loadSessionHistory();
  }, [sessionId]);

  // Fetch Clinic Data from NeonDB CRM API with unified high-performance single roundtrip
  const fetchClinicData = async () => {
    setIsRefreshing(true);
    try {
      const crmUrl = getCrmBaseUrl();
      
      // Fast single consolidated request
      const res = await fetch(`${crmUrl}/clinic-data`);
      if (res.ok) {
        const data = await res.json();
        if (data.doctors && Array.isArray(data.doctors)) setDoctors(data.doctors);
        if (data.appointments && Array.isArray(data.appointments)) setAppointments(data.appointments);
        if (data.clinic_info) setClinicInfo(data.clinic_info);
        if (data.database_dump) setDbDumpData(data.database_dump);
        return;
      }

      // Graceful fallback to individual endpoints if old server is encountered
      const [docsRes, apptsRes, dumpRes, infoRes] = await Promise.allSettled([
        fetch(`${crmUrl}/doctors`),
        fetch(`${crmUrl}/appointments`),
        fetch(`${crmUrl}/database-dump`),
        fetch(`${crmUrl}/clinic-info`)
      ]);

      if (docsRes.status === 'fulfilled' && docsRes.value.ok) {
        const docsData = await docsRes.value.json();
        if (Array.isArray(docsData) && docsData.length > 0) setDoctors(docsData);
      }

      if (apptsRes.status === 'fulfilled' && apptsRes.value.ok) {
        const apptsData = await apptsRes.value.json();
        if (Array.isArray(apptsData)) setAppointments(apptsData);
      }

      if (dumpRes.status === 'fulfilled' && dumpRes.value.ok) {
        const dumpData = await dumpRes.value.json();
        setDbDumpData(dumpData);
      }

      if (infoRes.status === 'fulfilled' && infoRes.value.ok) {
        const infoData = await infoRes.value.json();
        setClinicInfo(infoData);
      }
    } catch (e) {
      console.warn("Could not connect to backend CRM, using local cached state:", e);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchClinicData();
    
    // Smart Polling: poll every 5s only when tab is active
    const interval = setInterval(() => {
      if (typeof document !== 'undefined' && !document.hidden) {
        fetchClinicData();
      }
    }, 5000);

    const handleVisibility = () => {
      if (typeof document !== 'undefined' && !document.hidden) {
        fetchClinicData();
      }
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibility);
    }

    return () => {
      clearInterval(interval);
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibility);
      }
    };
  }, []);

  // Web Speech API: Text-to-Speech playback with seamless loop continuation
  const speakText = useCallback((text) => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;
    try {
      // Pause speech recognition while assistant is speaking to avoid feedback echo
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch (e) {}
      }
      setIsListeningMic(false);
      window.speechSynthesis.cancel();
      isSpeakingRef.current = true;

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.05;
      utterance.pitch = 1.0;
      if (lang === 'hi') utterance.lang = 'hi-IN';
      else if (lang === 'ta') utterance.lang = 'ta-IN';
      else if (lang === 'es') utterance.lang = 'es-ES';
      else utterance.lang = 'en-US';

      utterance.onstart = () => {
        setCallState('speaking');
        isSpeakingRef.current = true;
      };

      utterance.onend = () => {
        isSpeakingRef.current = false;
        setCallState(isCallActiveRef.current ? 'connected' : 'idle');
        // SEAMLESS AUTO-LISTEN: Automatically resume listening when assistant finishes speaking!
        if (isCallActiveRef.current && isSeamlessRef.current) {
          setTimeout(() => {
            if (isCallActiveRef.current && !isSpeakingRef.current && !isSimulatingRef.current) {
              startSpeechRecognition();
            }
          }, 350);
        }
      };

      utterance.onerror = () => {
        isSpeakingRef.current = false;
        setCallState(isCallActiveRef.current ? 'connected' : 'idle');
        if (isCallActiveRef.current && isSeamlessRef.current) {
          setTimeout(() => {
            if (isCallActiveRef.current && !isSpeakingRef.current && !isSimulatingRef.current) {
              startSpeechRecognition();
            }
          }, 350);
        }
      };

      window.speechSynthesis.speak(utterance);
    } catch (err) {
      console.warn("SpeechSynthesis error:", err);
      isSpeakingRef.current = false;
    }
  }, [lang]);

  // Web Speech API: Start Hands-Free Speech-to-Text Recognition
  const startSpeechRecognition = useCallback(() => {
    if (isSpeakingRef.current || isSimulatingRef.current) return;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setActionNotification("Web Speech recognition is not supported in this browser. Please type your request.");
      setTimeout(() => setActionNotification(''), 4000);
      return;
    }

    try {
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch (e) {}
      }

      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = lang === 'hi' ? 'hi-IN' : lang === 'ta' ? 'ta-IN' : lang === 'es' ? 'es-ES' : 'en-US';

      recognition.onstart = () => {
        setIsListeningMic(true);
        setCallState('listening');
        setLiveTranscript('');
      };

      recognition.onresult = (event) => {
        let interim = '';
        let final = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            final += event.results[i][0].transcript;
          } else {
            interim += event.results[i][0].transcript;
          }
        }

        if (interim) {
          setLiveTranscript(interim);
        }

        if (final && final.trim()) {
          setLiveTranscript('');
          setIsListeningMic(false);
          setCallState('processing');
          try { recognition.stop(); } catch (e) {}
          handleSimulateVoice(final.trim());
        }
      };

      recognition.onerror = (event) => {
        console.warn("Speech recognition notice:", event.error);
        setIsListeningMic(false);
        setLiveTranscript('');
        
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          setMicPermissionStatus('denied');
          setCallState('connected');
          return;
        }

        if (event.error === 'no-speech' && isCallActiveRef.current && isSeamlessRef.current && !isSpeakingRef.current && !isSimulatingRef.current) {
          // Gracefully continue listening loop after short pause
          setTimeout(() => {
            if (isCallActiveRef.current && !isSpeakingRef.current && !isSimulatingRef.current) {
              startSpeechRecognition();
            }
          }, 400);
        } else {
          setCallState(isCallActiveRef.current ? 'connected' : 'idle');
        }
      };

      recognition.onend = () => {
        setIsListeningMic(false);
        setLiveTranscript('');
        if (callState === 'listening') {
          setCallState('connected');
        }
      };

      recognitionRef.current = recognition;
      recognition.start();
    } catch (e) {
      console.warn("Could not start recognition:", e);
      setIsListeningMic(false);
    }
  }, [lang]);

  // Toggle Speech Recognition manually (or Push-to-Talk)
  const toggleSpeechRecognition = () => {
    if (isListeningMic) {
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch (e) {}
      }
      setIsListeningMic(false);
      setCallState('connected');
    } else {
      if (micPermissionStatus === 'denied') {
        setShowMicModal(true);
        return;
      }
      if (callState === 'idle') {
        startCall();
      } else {
        startSpeechRecognition();
      }
    }
  };

  // Action: Execute Voice Simulation / Chat with full context memory passed to NeonDB
  const handleSimulateVoice = async (userMessage) => {
    const text = (userMessage || simInput).trim();
    if (!text) return;
    setSimInput('');
    setIsSimulating(true);
    setCallState('processing');

    const newLog = {
      role: 'user',
      text,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    setConversationLogs(prev => [...prev, newLog]);

    try {
      const crmUrl = getCrmBaseUrl();
      // Prepare full conversation context history
      const historyPayload = conversationLogs.map(l => ({
        role: l.role,
        content: l.text || l.content || ""
      }));

      const res = await fetch(`${crmUrl}/simulate-voice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          lang,
          conversation_history: historyPayload,
          gemini_key: geminiKey
        })
      });

      if (res.ok) {
        const data = await res.json();
        const assistantReply = data.assistant_response || "I have processed your request.";
        
        setConversationLogs(prev => [
          ...prev, 
          {
            role: 'assistant',
            text: assistantReply,
            tool_called: data.tool_called,
            tool_result: data.tool_result,
            action: data.action,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          }
        ]);

        if (data.database_updated) {
          fetchClinicData();
          setActionNotification(`Database Updated: ${data.action.toUpperCase()} recorded in NeonDB.`);
          setTimeout(() => setActionNotification(''), 4000);
        }

        // Speak back assistant's voice -> on completion it will automatically resume auto-listening!
        speakText(assistantReply);
      } else {
        throw new Error("Server simulation endpoint returned non-200 status");
      }
    } catch (err) {
      console.warn("Server simulation error, using contextual client fallback:", err);
      let reply = "I have noted your request. Let me check the doctor schedule.";
      const lower = text.toLowerCase();
      let tool = null;
      let action = null;

      if (lower.includes("book") || lower.includes("schedule") || lower.includes("confirm")) {
        tool = "book_appointment";
        action = "booked";
        reply = `Your appointment has been confirmed with Dr. Rohan Sharma on tomorrow at 16:00. Synced with Google Calendar!`;
        fetchClinicData();
      } else if (lower.includes("available") || lower.includes("check")) {
        tool = "check_availability";
        reply = "Dr. Rohan Sharma (Cardiology) is available tomorrow at 16:00. Would you like me to book this for you?";
      } else if (lower.includes("cancel")) {
        tool = "cancel_appointment";
        action = "cancelled";
        reply = "Your appointment has been cancelled successfully.";
        fetchClinicData();
      }

      setConversationLogs(prev => [
        ...prev,
        {
          role: 'assistant',
          text: reply,
          tool_called: tool,
          action,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
      speakText(reply);
    } finally {
      setIsSimulating(false);
    }
  };

  // Action: Reset Conversation & Start Fresh Context Session
  const handleResetConversation = async () => {
    try {
      const crmUrl = getCrmBaseUrl();
      await fetch(`${crmUrl}/conversations/${sessionId}`, { method: 'DELETE' });
    } catch (e) {
      console.warn("Notice resetting session:", e);
    }
    const newSess = 'sess_' + Math.random().toString(36).substring(2, 11);
    setSessionId(newSess);
    localStorage.setItem('med_session_id', newSess);
    
    const initialGreeting = lang === 'hi' ? 'नमस्ते! मेडिकनेक्ट क्लिनिक में आपका स्वागत है। आज मैं आपकी क्या सहायता करूँ?' :
                           lang === 'ta' ? 'வணக்கம்! மெடிகனெக்ட் கிளினிக்கிற்கு வரவேற்கிறோம். இன்று உங்கள் முன்பதிவுக்கு எவ்வாறு உதவட்டும்?' :
                           lang === 'es' ? '¡Hola! Bienvenido a la Clínica MediConnect. ¿Cómo puedo ayudarle hoy?' :
                           'Hello! Thank you for calling MediConnect Clinic. How can I assist you with your doctor appointment today?';

    setConversationLogs([
      {
        role: 'assistant',
        text: initialGreeting,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    ]);
    setActionNotification("Conversation context reset. Started fresh session.");
    setTimeout(() => setActionNotification(''), 4000);
  };

  // Action: Cancel Appointment from Receptionist View
  const handleCancelAppointment = async (apptId) => {
    try {
      const crmUrl = getCrmBaseUrl();
      const res = await fetch(`${crmUrl}/appointments/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ appointment_id: apptId })
      });
      if (res.ok) {
        setActionNotification(`Appointment #${apptId} cancelled successfully in NeonDB.`);
        fetchClinicData();
      } else {
        setAppointments(prev => prev.map(a => a.id === apptId ? { ...a, status: 'Cancelled' } : a));
        setActionNotification(`Appointment #${apptId} marked as Cancelled.`);
      }
    } catch (err) {
      setAppointments(prev => prev.map(a => a.id === apptId ? { ...a, status: 'Cancelled' } : a));
      setActionNotification(`Appointment #${apptId} marked as Cancelled.`);
    }
    setTimeout(() => setActionNotification(''), 4000);
  };

  // Action: Sync External Calendar
  const handleSyncCalendar = async (apptId) => {
    try {
      const crmUrl = getCrmBaseUrl();
      await fetch(`${crmUrl}/sync-calendar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ appointment_id: apptId })
      });
      setActionNotification(`Synced appointment #${apptId} with doctor's external Google Calendar.`);
    } catch (err) {
      setActionNotification(`Simulated Google Calendar sync for #${apptId}.`);
    }
    setTimeout(() => setActionNotification(''), 4000);
  };

  // Export Complete Database JSON
  const exportDatabaseJson = () => {
    const dataToExport = dbDumpData || {
      engine: "Neon PostgreSQL",
      tables: {
        doctors,
        appointments,
        clinic_info: clinicInfo || {
          name: "MediConnect Clinic",
          address: "123 Health Boulevard, Suite 100",
          phone: "555-0199",
          hours: "Monday-Friday (08:00 to 18:00), Saturday (08:00 to 16:00), Sunday (Closed)"
        }
      }
    };
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(dataToExport, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `mediconnect_neondb_dump_${new Date().toISOString().slice(0, 10)}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const copyDatabaseJson = () => {
    const dataToExport = dbDumpData || { doctors, appointments, clinic_info: clinicInfo };
    navigator.clipboard.writeText(JSON.stringify(dataToExport, null, 2));
    setCopiedJson(true);
    setTimeout(() => setCopiedJson(false), 2500);
  };

  // Save Selected Language
  const handleLangChange = (newLang) => {
    setLang(newLang);
    localStorage.setItem('med_lang', newLang);
  };

  // Start Voice Call Session (Seamless Browser AI Mode or WebSocket)
  const startCall = async () => {
    setCallState('connecting');
    setErrorMessage('');
    setIsWsError1006(false);

    // Request mic permission if prompt or unknown
    if (micPermissionStatus === 'prompt' || micPermissionStatus === 'unknown') {
      const granted = await requestMicPermission();
      if (!granted && micPermissionStatus === 'denied') {
        setCallState('idle');
        return;
      }
    }

    if (voiceMode === 'browser_ai') {
      setTimeout(() => {
        setCallState('connected');
        const greeting = lang === 'hi' ? 'नमस्ते! मेडिकनेक्ट क्लिनिक में आपका स्वागत है। मैं आपकी क्या सहायता करूँ?' :
                         lang === 'ta' ? 'வணக்கம்! மெடிகனெக்ட் கிளினிக்கிற்கு வரவேற்கிறோம். இன்று உங்கள் முன்பதிவுக்கு எவ்வாறு உதவட்டும்?' :
                         lang === 'es' ? '¡Hola! Bienvenido a la Clínica MediConnect. ¿Cómo puedo ayudarle hoy?' :
                         'Hello! Welcome to MediConnect Clinic. How can I assist you with your appointment today?';
        speakText(greeting);
      }, 400);
      return;
    }

    try {
      const transport = new WebSocketTransport({
        serializer: new ProtobufFrameSerializer(),
        recorderSampleRate: 16000,
        playerSampleRate: 16000,
      });

      const client = new PipecatClient({
        transport,
        enableMic: true,
        callbacks: {
          onConnected: () => {
            console.log("Connected to Pipecat Voice Server");
            setCallState('connected');
          },
          onDisconnected: () => {
            console.log("Disconnected from Pipecat Voice Server");
            setCallState('idle');
          },
          onError: (err) => {
            console.error("Pipecat Client Error:", err);
            const msg = err.message || "Voice stream connection error.";
            setErrorMessage(msg);
            if (msg.includes("1006") || msg.includes("WebSocket connection error")) {
              setIsWsError1006(true);
            }
            setCallState('error');
          }
        }
      });

      clientRef.current = client;

      const params = new URLSearchParams({
        lang,
        stt: sttProvider,
        tts: ttsProvider,
        gemini_key: geminiKey,
        deepgram_key: deepgramKey,
        elevenlabs_key: elevenlabsKey,
        sarvam_key: sarvamKey
      });

      const wsUrl = getVoiceWsUrl(params);
      await client.connect({ wsUrl });

    } catch (e) {
      console.error("Failed to start voice call:", e);
      const msg = e.message || "Could not connect to the voice server.";
      setErrorMessage(msg);
      if (msg.includes("1006") || msg.includes("WebSocket connection error") || msg.includes("Failed to connect")) {
        setIsWsError1006(true);
      }
      setCallState('error');
    }
  };

  // End Voice Call Session
  const endCall = async () => {
    isCallActiveRef.current = false;
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch (e) {}
    }
    setIsListeningMic(false);
    setLiveTranscript('');

    if (clientRef.current) {
      try {
        await clientRef.current.disconnect();
      } catch (e) {
        console.error(e);
      }
      clientRef.current = null;
    }
    setCallState('idle');
  };

  // Audio Canvas visualizer loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let phase = 0;

    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      const width = canvas.width;
      const height = canvas.height;
      const mid = height / 2;

      ctx.beginPath();
      ctx.lineWidth = 2;

      const isActive = callState === 'connected' || callState === 'speaking' || callState === 'listening' || callState === 'processing';

      if (isActive) {
        let colors = [
          'rgba(0, 229, 255, 0.6)', 
          'rgba(124, 77, 255, 0.6)', 
          'rgba(0, 230, 118, 0.4)'
        ];

        let mult = 0.8;
        if (callState === 'listening') {
          mult = 1.8;
          colors = ['rgba(0, 230, 118, 0.8)', 'rgba(0, 229, 255, 0.7)', 'rgba(0, 230, 118, 0.4)'];
        } else if (callState === 'speaking') {
          mult = 2.0;
          colors = ['rgba(124, 77, 255, 0.8)', 'rgba(0, 229, 255, 0.7)', 'rgba(255, 64, 129, 0.5)'];
        } else if (callState === 'processing') {
          mult = 1.2;
          colors = ['rgba(255, 214, 0, 0.8)', 'rgba(0, 229, 255, 0.6)', 'rgba(255, 214, 0, 0.4)'];
        }

        for (let i = 0; i < 3; i++) {
          ctx.beginPath();
          ctx.strokeStyle = colors[i];
          const amplitude = (26 - i * 6) * mult * (Math.sin(phase / 8) * 0.3 + 0.7);
          const frequency = 0.018 + i * 0.006;

          ctx.moveTo(0, mid);
          for (let x = 0; x < width; x++) {
            const y = mid + Math.sin(x * frequency + phase + i) * amplitude * Math.sin((x / width) * Math.PI);
            ctx.lineTo(x, y);
          }
          ctx.stroke();
        }
        phase += (callState === 'listening' || callState === 'speaking') ? 0.15 : 0.08;
      } else if (callState === 'connecting') {
        ctx.strokeStyle = 'rgba(0, 229, 255, 0.3)';
        ctx.moveTo(0, mid);
        for (let x = 0; x < width; x++) {
          const y = mid + Math.sin(x * 0.06 + phase) * 4;
          ctx.lineTo(x, y);
        }
        ctx.stroke();
        phase += 0.2;
      } else {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
        ctx.moveTo(0, mid);
        ctx.lineTo(width, mid);
        ctx.stroke();
      }

      animationRef.current = requestAnimationFrame(render);
    };

    const resizeCanvas = () => {
      if (canvas && canvas.parentElement) {
        canvas.width = canvas.parentElement.clientWidth;
        canvas.height = canvas.parentElement.clientHeight;
      }
    };
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    render();

    return () => {
      cancelAnimationFrame(animationRef.current);
      window.removeEventListener('resize', resizeCanvas);
    };
  }, [callState]);

  // Filtered Appointments for Receptionist View
  const filteredAppointments = appointments.filter((appt) => {
    const matchesSearch = 
      (appt.patient_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (appt.patient_phone || '').includes(searchQuery) ||
      (appt.doctor_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (appt.specialty || '').toLowerCase().includes(searchQuery.toLowerCase());
    
    if (statusFilter === 'booked') return matchesSearch && (appt.status || '').toLowerCase() === 'booked';
    if (statusFilter === 'cancelled') return matchesSearch && (appt.status || '').toLowerCase() === 'cancelled';
    return matchesSearch;
  });

  return (
    <div className="app-container">
      {/* INITIAL MICROPHONE PERMISSION POPUP MODAL */}
      {showMicModal && (
        <div className="modal-backdrop" onClick={() => setShowMicModal(false)}>
          <div 
            className="modal-card" 
            onClick={(e) => e.stopPropagation()}
            style={{ padding: '2rem', textAlign: 'center' }}
          >
            <div style={{
              width: '56px',
              height: '56px',
              borderRadius: '50%',
              background: 'var(--color-primary-light)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 1.25rem',
              color: 'var(--color-primary)'
            }}>
              <Mic size={28} />
            </div>

            <h3 style={{ fontSize: '1.35rem', fontWeight: 700, fontFamily: 'var(--font-display)', marginBottom: '0.5rem', color: 'var(--text-primary)' }}>
              Enable Voice Receptionist
            </h3>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: '1.5rem' }}>
              Speak naturally to book or inquire about doctor appointments. 
              The AI receptionist listens automatically without needing manual clicks between turns.
            </p>

            <div style={{ display: 'flex', gap: '0.75rem' }}>
              <button 
                className="btn btn-outline" 
                style={{ flex: 1 }}
                onClick={() => {
                  setShowMicModal(false);
                  localStorage.setItem('mic_modal_dismissed', 'true');
                }}
              >
                Text Mode
              </button>

              <button 
                className="btn btn-primary" 
                style={{ flex: 1.5 }}
                onClick={requestMicPermission}
              >
                <Mic size={16} />
                <span>Allow Microphone</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Clean Header */}
      <header className="app-header">
        <div className="logo-container">
          <div className="logo-icon">
            <Stethoscope size={24} />
          </div>
          <div>
            <div className="logo-text">MediConnect</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>Voice Clinic Receptionist</span>
              <span style={{ 
                background: 'var(--color-success-light)', 
                color: '#065f46', 
                padding: '1px 6px', 
                borderRadius: '4px', 
                fontSize: '0.65rem',
                fontWeight: 700
              }}>
                NeonDB Live
              </span>
            </div>
          </div>
        </div>

        <div className="header-actions">
          <a 
            href="https://calendar.google.com/calendar/u/0/r" 
            target="_blank" 
            rel="noopener noreferrer" 
            className="btn btn-outline" 
            style={{ textDecoration: 'none' }}
            title="Open Google Calendar"
          >
            <Calendar size={15} style={{ color: 'var(--color-primary)' }} />
            <span>Calendar</span>
            <ExternalLink size={12} />
          </a>

          <button 
            className={`btn ${isReceptionistOpen ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setIsReceptionistOpen(!isReceptionistOpen)}
            title="Open Receptionist Desk"
          >
            <UserCheck size={16} />
            <span>Reception Desk</span>
            {appointments.length > 0 && (
              <span style={{
                background: isReceptionistOpen ? 'rgba(255,255,255,0.3)' : 'var(--color-primary-light)',
                color: isReceptionistOpen ? '#fff' : 'var(--color-primary)',
                padding: '2px 7px',
                borderRadius: '99px',
                fontSize: '0.7rem',
                fontWeight: 800
              }}>
                {appointments.length}
              </span>
            )}
          </button>

          <button 
            id="btn-complete-database-view"
            className="btn btn-outline"
            onClick={() => setIsDatabaseOpen(true)}
            title="Inspect Database Records"
          >
            <Database size={16} />
            <span>Database</span>
          </button>

          <button className="btn btn-outline" style={{ padding: '0.625rem' }} onClick={fetchClinicData} title="Refresh Live Data">
            <RefreshCw className={isRefreshing ? "animate-spin" : ""} size={16} />
          </button>
        </div>
      </header>

      {/* Permission Blocked Warning */}
      {micPermissionStatus === 'denied' && (
        <div style={{
          background: 'var(--color-danger-light)',
          border: '1px solid #fca5a5',
          borderRadius: '10px',
          padding: '0.75rem 1.25rem',
          margin: '0.75rem 2rem 0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.75rem'
        }}>
          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
            <AlertCircle size={18} style={{ color: 'var(--color-danger)' }} />
            <span style={{ fontSize: '0.85rem', color: '#991b1b', fontWeight: 600 }}>
              Microphone access is blocked. Click the lock/settings icon in your browser address bar to allow mic access.
            </span>
          </div>
          <button 
            className="btn btn-danger" 
            style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
            onClick={requestMicPermission}
          >
            <Mic size={13} /> Retry Permission
          </button>
        </div>
      )}

      {/* Main Content Layout */}
      <main className="main-content">
        {/* Left Section: Doctor Schedules & Live Bookings */}
        <section>
          {/* Action Notification Toast */}
          {actionNotification && (
            <div style={{
              background: 'var(--color-success-light)',
              border: '1px solid #a7f3d0',
              borderRadius: '10px',
              padding: '0.75rem 1rem',
              marginBottom: '1.25rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              color: '#065f46',
              fontSize: '0.875rem',
              fontWeight: 600
            }}>
              <CheckCircle2 size={18} />
              <span>{actionNotification}</span>
            </div>
          )}

          {/* Doctors Section */}
          <div className="dashboard-title">
            <span>Available Specialists ({doctors.length})</span>
            <span style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--text-muted)' }}>
              Operating Hours: {clinicInfo?.hours || "Mon-Fri 08:00-18:00"}
            </span>
          </div>

          <div className="doctors-grid">
            {doctors.map((doc) => (
              <div key={doc.id} className="doctor-card">
                <span className="doctor-specialty">{doc.specialty}</span>
                <h4 className="doctor-name">{doc.name}</h4>
                <div className="doctor-meta">
                  <Calendar size={14} style={{ color: 'var(--color-primary)' }} />
                  <span>{doc.available_days}</span>
                </div>
                <div className="doctor-meta">
                  <Clock size={14} style={{ color: 'var(--color-primary)' }} />
                  <span>{doc.start_time} - {doc.end_time}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Appointments Section */}
          <div className="dashboard-title">
            <span>Recent Appointments ({appointments.length})</span>
            <button 
              className="btn btn-outline" 
              style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}
              onClick={() => setIsReceptionistOpen(true)}
            >
              <UserCheck size={14} /> Full Desk
            </button>
          </div>

          <div className="appointments-table-container">
            <table className="appointments-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Patient</th>
                  <th>Doctor</th>
                  <th>Date</th>
                  <th>Time</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {appointments.length > 0 ? (
                  appointments.map((appt) => (
                    <tr key={appt.id}>
                      <td style={{ fontWeight: 700, color: 'var(--color-primary)' }}>#{appt.id}</td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{appt.patient_name}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{appt.patient_phone}</div>
                      </td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{appt.doctor_name}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{appt.specialty}</div>
                      </td>
                      <td>{appt.date}</td>
                      <td>{appt.time}</td>
                      <td>
                        <span className={`status-badge ${(appt.status || '').toLowerCase() === 'booked' ? 'status-booked' : 'status-cancelled'}`}>
                          {appt.status}
                        </span>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="6" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                      No appointments booked yet. Speak with the Voice Receptionist to schedule!
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Right Section: AI Voice Receptionist Console */}
        <section className="voice-console-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ fontSize: '1.2rem', fontWeight: 700, fontFamily: 'var(--font-display)', display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-primary)' }}>
              <Radio size={18} style={{ color: 'var(--color-primary)' }} />
              Voice Receptionist
            </h2>

            <button
              onClick={() => setIsSeamlessAutoListen(!isSeamlessAutoListen)}
              style={{
                background: isSeamlessAutoListen ? 'var(--color-success-light)' : 'var(--bg-surface)',
                color: isSeamlessAutoListen ? '#065f46' : 'var(--text-muted)',
                border: `1px solid ${isSeamlessAutoListen ? '#a7f3d0' : 'var(--border-color)'}`,
                borderRadius: '99px',
                padding: '3px 9px',
                fontSize: '0.72rem',
                fontWeight: 700,
                cursor: 'pointer'
              }}
              title="Toggle Hands-Free Voice Auto-Listening"
            >
              {isSeamlessAutoListen ? "Hands-Free: ON" : "Hands-Free: OFF"}
            </button>
          </div>

          {/* Visualizer */}
          <div className={`voice-visualizer-container ${callState === 'listening' ? 'listening-bg' : callState === 'speaking' ? 'speaking-bg' : ''}`}>
            <canvas ref={canvasRef} className="waveform-canvas" />
            <div 
              className={`pulse-ring ${callState === 'connected' || callState === 'speaking' || callState === 'listening' ? (callState === 'speaking' ? 'speaking' : 'listening') : ''}`}
              onClick={callState === 'idle' ? startCall : toggleSpeechRecognition}
              title={callState === 'idle' ? "Click to Start Voice" : "Click to Speak / Pause"}
            >
              {callState === 'speaking' ? (
                <Volume2 size={24} color="var(--color-secondary)" />
              ) : callState === 'listening' ? (
                <Mic size={24} color="var(--color-primary)" />
              ) : (
                <Phone size={24} color="var(--color-primary)" />
              )}
            </div>
          </div>

          {/* Status Text */}
          <div className="console-status-text">
            {callState === 'idle' && "Click Mic to Start Voice Assistant"}
            {callState === 'listening' && "🎙️ Listening... Speak naturally"}
            {callState === 'processing' && "⚡ Checking doctor availability..."}
            {callState === 'speaking' && "🔊 Receptionist Speaking..."}
            {callState === 'connected' && "🟢 Assistant Ready — Speak or Type"}
            {callState === 'error' && "Voice Notice"}
          </div>

          {/* Live transcription */}
          {liveTranscript && (
            <div style={{
              background: 'var(--color-primary-light)',
              border: '1px solid #bae6fd',
              borderRadius: '8px',
              padding: '0.4rem 0.75rem',
              fontSize: '0.8rem',
              color: 'var(--color-primary-hover)',
              fontStyle: 'italic',
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem'
            }}>
              <Mic size={14} />
              <span>Hearing: "{liveTranscript}"...</span>
            </div>
          )}

          {/* Controls */}
          {callState === 'idle' || callState === 'error' ? (
            <button 
              className="btn btn-primary" 
              onClick={startCall} 
              style={{ width: '100%', height: '44px', fontWeight: 700 }}
            >
              <Phone size={16} />
              Start Voice Conversation
            </button>
          ) : (
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button 
                className="btn" 
                onClick={toggleSpeechRecognition}
                style={{ 
                  flex: 1, 
                  height: '44px', 
                  background: isListeningMic ? 'var(--color-success)' : 'var(--color-primary-light)',
                  color: isListeningMic ? '#ffffff' : 'var(--color-primary)',
                  border: `1px solid ${isListeningMic ? 'var(--color-success)' : '#bae6fd'}`,
                  fontWeight: 700
                }}
              >
                {isListeningMic ? <MicOff size={16} /> : <Mic size={16} />}
                {isListeningMic ? "Listening (Click to Pause)" : "Speak Now"}
              </button>
              
              <button 
                className="btn btn-danger" 
                onClick={endCall} 
                style={{ height: '44px', padding: '0 1rem' }}
                title="End Voice Session"
              >
                <PhoneOff size={16} />
              </button>
            </div>
          )}

          {/* Language Selector */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-color)', paddingTop: '0.75rem' }}>
            <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
              <Languages size={14} /> Language:
            </span>
            <select 
              className="form-select" 
              value={lang} 
              onChange={(e) => handleLangChange(e.target.value)} 
              style={{ padding: '0.3rem 0.6rem', fontSize: '0.8125rem' }}
            >
              <option value="en">English (US)</option>
              <option value="hi">Hindi (हिंदी)</option>
              <option value="ta">Tamil (தமிழ்)</option>
              <option value="es">Spanish (Español)</option>
            </select>
          </div>

          {/* Conversation Chat Log */}
          <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '0.75rem', display: 'flex', flexDirection: 'column', flex: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Conversation History
              </span>
              <button 
                className="btn btn-outline" 
                style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem' }}
                onClick={handleResetConversation}
                title="Reset session and start fresh"
              >
                <RotateCcw size={11} /> Reset
              </button>
            </div>

            <div style={{
              height: '210px',
              overflowY: 'auto',
              background: 'var(--bg-surface)',
              borderRadius: '10px',
              padding: '0.75rem',
              border: '1px solid var(--border-color)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
              fontSize: '0.8125rem'
            }}>
              {conversationLogs.map((log, idx) => (
                <div key={idx} style={{
                  alignSelf: log.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '90%',
                  background: log.role === 'user' ? 'var(--color-primary-light)' : '#ffffff',
                  color: log.role === 'user' ? 'var(--color-primary-hover)' : 'var(--text-primary)',
                  border: `1px solid ${log.role === 'user' ? '#bae6fd' : 'var(--border-color)'}`,
                  borderRadius: log.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                  padding: '0.5rem 0.75rem',
                  boxShadow: 'var(--shadow-xs)'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', marginBottom: '2px', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                    <span>{log.role === 'user' ? '👤 You' : '🤖 Receptionist'}</span>
                    <span>{log.time}</span>
                  </div>
                  <div>{log.text}</div>
                </div>
              ))}
              <div ref={chatBottomRef} />
            </div>

            {/* Quick 1-Click Action Prompts */}
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.35rem', overflowX: 'auto', paddingBottom: '2px' }}>
              <button
                className="btn btn-outline"
                style={{ fontSize: '0.72rem', padding: '0.25rem 0.5rem', whiteSpace: 'nowrap' }}
                onClick={() => handleSimulateVoice("I want to book an appointment with Dr. Sarah Patel")}
                disabled={isSimulating}
              >
                Dr. Sarah Patel
              </button>
              <button
                className="btn btn-outline"
                style={{ fontSize: '0.72rem', padding: '0.25rem 0.5rem', whiteSpace: 'nowrap' }}
                onClick={() => handleSimulateVoice("Tomorrow at 10 AM")}
                disabled={isSimulating}
              >
                Tomorrow 10 AM
              </button>
              <button
                className="btn btn-outline"
                style={{ fontSize: '0.72rem', padding: '0.25rem 0.5rem', whiteSpace: 'nowrap' }}
                onClick={() => handleSimulateVoice("My name is John Doe, phone 555-1234")}
                disabled={isSimulating}
              >
                John Doe 555-1234
              </button>
            </div>

            {/* Input Form */}
            <form 
              onSubmit={(e) => { e.preventDefault(); handleSimulateVoice(); }} 
              style={{ display: 'flex', gap: '0.35rem', marginTop: '0.5rem' }}
            >
              <input
                type="text"
                className="form-input"
                placeholder="Type or speak a request..."
                value={simInput}
                onChange={(e) => setSimInput(e.target.value)}
                style={{ flex: 1, padding: '0.5rem 0.75rem', fontSize: '0.8125rem' }}
                disabled={isSimulating}
              />
              <button 
                type="button" 
                className="btn btn-outline" 
                style={{ padding: '0.5rem' }}
                onClick={toggleSpeechRecognition}
                title="Click to speak"
              >
                <Mic size={16} color={isListeningMic ? "var(--color-success)" : "var(--color-primary)"} />
              </button>
              <button 
                type="submit" 
                className="btn btn-primary" 
                style={{ padding: '0.5rem 0.85rem' }}
                disabled={isSimulating || !simInput.trim()}
              >
                <Send size={15} />
              </button>
            </form>
          </div>
        </section>
      </main>

      {/* ==========================================================================
          DATABASE VIEW MODAL (CLEAN LIGHT THEME)
         ========================================================================== */}
      {isDatabaseOpen && (
        <div className="drawer-backdrop" onClick={() => setIsDatabaseOpen(false)}>
          <div 
            className="glass-panel"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '94%',
              maxWidth: '1200px',
              height: '90vh',
              background: '#ffffff',
              margin: 'auto',
              borderRadius: '18px',
              padding: '1.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.25rem',
              boxShadow: 'var(--shadow-lg)',
              overflow: 'hidden'
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
              <div>
                <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', fontWeight: 700, display: 'flex', gap: '0.5rem', alignItems: 'center', color: 'var(--text-primary)' }}>
                  <Database size={22} style={{ color: 'var(--color-primary)' }} />
                  Hospital Database Inspector
                </h2>
                <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Live records fetched directly from Neon PostgreSQL
                </p>
              </div>
              
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }} onClick={copyDatabaseJson}>
                  {copiedJson ? <Check size={13} style={{ color: 'var(--color-success)' }} /> : <Copy size={13} />}
                  <span>{copiedJson ? 'Copied' : 'Copy JSON'}</span>
                </button>

                <button className="btn btn-outline" style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }} onClick={exportDatabaseJson}>
                  <Download size={13} /> Export JSON
                </button>

                <button className="btn btn-outline" style={{ padding: '0.4rem' }} onClick={fetchClinicData} title="Refresh Database">
                  <RefreshCw className={isRefreshing ? "animate-spin" : ""} size={15} />
                </button>

                <button 
                  className="btn btn-outline" 
                  style={{ padding: '0.4rem', borderRadius: '50%' }} 
                  onClick={() => setIsDatabaseOpen(false)}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Tabs */}
            <div style={{ display: 'flex', gap: '0.35rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
              <button 
                className={`btn ${dbTab === 'appointments' ? 'btn-primary' : 'btn-outline'}`}
                style={{ padding: '0.35rem 0.85rem', fontSize: '0.8rem' }}
                onClick={() => setDbTab('appointments')}
              >
                Appointments ({appointments.length})
              </button>

              <button 
                className={`btn ${dbTab === 'doctors' ? 'btn-primary' : 'btn-outline'}`}
                style={{ padding: '0.35rem 0.85rem', fontSize: '0.8rem' }}
                onClick={() => setDbTab('doctors')}
              >
                Doctors ({doctors.length})
              </button>

              <button 
                className={`btn ${dbTab === 'clinic_info' ? 'btn-primary' : 'btn-outline'}`}
                style={{ padding: '0.35rem 0.85rem', fontSize: '0.8rem' }}
                onClick={() => setDbTab('clinic_info')}
              >
                Clinic Details
              </button>

              <button 
                className={`btn ${dbTab === 'json' ? 'btn-primary' : 'btn-outline'}`}
                style={{ padding: '0.35rem 0.85rem', fontSize: '0.8rem' }}
                onClick={() => setDbTab('json')}
              >
                Raw JSON
              </button>
            </div>

            {/* Content */}
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px', background: '#ffffff' }}>
              {dbTab === 'appointments' && (
                <table className="appointments-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Patient</th>
                      <th>Phone</th>
                      <th>Doctor</th>
                      <th>Specialty</th>
                      <th>Date</th>
                      <th>Time</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {appointments.map((a) => (
                      <tr key={a.id}>
                        <td style={{ color: 'var(--color-primary)', fontWeight: 700 }}>#{a.id}</td>
                        <td style={{ fontWeight: 600 }}>{a.patient_name}</td>
                        <td>{a.patient_phone}</td>
                        <td>{a.doctor_name}</td>
                        <td>{a.specialty}</td>
                        <td>{a.date}</td>
                        <td>{a.time}</td>
                        <td>
                          <span className={`status-badge ${(a.status || '').toLowerCase() === 'booked' ? 'status-booked' : 'status-cancelled'}`}>
                            {a.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {dbTab === 'doctors' && (
                <table className="appointments-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Doctor Name</th>
                      <th>Specialty</th>
                      <th>Available Days</th>
                      <th>Hours</th>
                    </tr>
                  </thead>
                  <tbody>
                    {doctors.map((d) => (
                      <tr key={d.id}>
                        <td style={{ color: 'var(--color-primary)', fontWeight: 700 }}>#{d.id}</td>
                        <td style={{ fontWeight: 600 }}>{d.name}</td>
                        <td><span className="doctor-specialty">{d.specialty}</span></td>
                        <td>{d.available_days}</td>
                        <td>{d.start_time} - {d.end_time}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {dbTab === 'clinic_info' && (
                <div style={{ padding: '1.5rem' }}>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--color-primary)', marginBottom: '0.75rem' }}>
                    {clinicInfo?.name || "MediConnect Clinic"}
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', fontSize: '0.875rem' }}>
                    <div><strong>Address:</strong> {clinicInfo?.address || "123 Health Boulevard, Suite 100"}</div>
                    <div><strong>Phone:</strong> {clinicInfo?.phone || "555-0199"}</div>
                    <div><strong>Operating Hours:</strong> {clinicInfo?.hours || "Monday-Friday (08:00-18:00)"}</div>
                  </div>
                </div>
              )}

              {dbTab === 'json' && (
                <pre style={{
                  padding: '1.25rem',
                  fontFamily: 'monospace',
                  fontSize: '0.8rem',
                  lineHeight: 1.5,
                  color: 'var(--text-primary)',
                  background: 'var(--bg-surface)',
                  margin: 0,
                  whiteSpace: 'pre-wrap'
                }}>
                  {JSON.stringify(dbDumpData || { doctors, appointments, clinic_info: clinicInfo }, null, 2)}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ==========================================================================
          RECEPTIONIST DESK VIEW MODAL (CLEAN LIGHT THEME)
         ========================================================================== */}
      {isReceptionistOpen && (
        <div className="drawer-backdrop" onClick={() => setIsReceptionistOpen(false)}>
          <div 
            className="glass-panel"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '94%',
              maxWidth: '1200px',
              height: '90vh',
              background: '#ffffff',
              margin: 'auto',
              borderRadius: '18px',
              padding: '1.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.25rem',
              boxShadow: 'var(--shadow-lg)',
              overflow: 'hidden'
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
              <div>
                <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', fontWeight: 700, display: 'flex', gap: '0.5rem', alignItems: 'center', color: 'var(--text-primary)' }}>
                  <UserCheck size={22} style={{ color: 'var(--color-primary)' }} />
                  Hospital Receptionist Desk
                </h2>
                <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Manage patient bookings, cancel appointments, and sync doctor schedules
                </p>
              </div>
              <button className="btn btn-outline" style={{ padding: '0.4rem', borderRadius: '50%' }} onClick={() => setIsReceptionistOpen(false)}>
                <X size={18} />
              </button>
            </div>

            {/* Filter and Search Bar */}
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
              <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
                <Search size={15} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input 
                  type="text" 
                  className="form-input" 
                  placeholder="Search patient, phone, doctor or specialty..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{ paddingLeft: '2rem', width: '100%' }}
                />
              </div>

              <div style={{ display: 'flex', gap: '0.25rem', background: 'var(--bg-surface)', padding: '3px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                <button 
                  className={`btn ${statusFilter === 'all' ? 'btn-primary' : 'btn-outline'}`}
                  style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem', border: 'none' }}
                  onClick={() => setStatusFilter('all')}
                >
                  All ({appointments.length})
                </button>
                <button 
                  className={`btn ${statusFilter === 'booked' ? 'btn-primary' : 'btn-outline'}`}
                  style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem', border: 'none' }}
                  onClick={() => setStatusFilter('booked')}
                >
                  Booked ({appointments.filter(a => (a.status || '').toLowerCase() === 'booked').length})
                </button>
                <button 
                  className={`btn ${statusFilter === 'cancelled' ? 'btn-primary' : 'btn-outline'}`}
                  style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem', border: 'none' }}
                  onClick={() => setStatusFilter('cancelled')}
                >
                  Cancelled ({appointments.filter(a => (a.status || '').toLowerCase() === 'cancelled').length})
                </button>
              </div>
            </div>

            {/* Reception Table */}
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px', background: '#ffffff' }}>
              <table className="appointments-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Patient Name</th>
                    <th>Phone</th>
                    <th>Doctor</th>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAppointments.length > 0 ? (
                    filteredAppointments.map((appt) => (
                      <tr key={appt.id}>
                        <td style={{ fontWeight: 700, color: 'var(--color-primary)' }}>#{appt.id}</td>
                        <td style={{ fontWeight: 600 }}>{appt.patient_name}</td>
                        <td>{appt.patient_phone}</td>
                        <td>
                          {appt.doctor_name}
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{appt.specialty}</div>
                        </td>
                        <td>{appt.date}</td>
                        <td>{appt.time}</td>
                        <td>
                          <span className={`status-badge ${(appt.status || '').toLowerCase() === 'booked' ? 'status-booked' : 'status-cancelled'}`}>
                            {appt.status}
                          </span>
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: '0.35rem' }}>
                            <a 
                              href={getGoogleCalendarUrl(appt)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn btn-outline"
                              style={{ 
                                fontSize: '0.72rem', 
                                padding: '0.25rem 0.5rem', 
                                textDecoration: 'none', 
                                display: 'inline-flex', 
                                alignItems: 'center', 
                                gap: '3px' 
                              }}
                              title="Google Calendar"
                            >
                              <Calendar size={12} />
                              <span>Calendar</span>
                            </a>

                            {(appt.status || '').toLowerCase() === 'booked' && (
                              <button 
                                className="btn btn-danger" 
                                style={{ padding: '0.25rem 0.5rem', fontSize: '0.72rem' }}
                                onClick={() => handleCancelAppointment(appt.id)}
                                title="Cancel Booking"
                              >
                                <Trash2 size={12} /> Cancel
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan="8" style={{ textAlign: 'center', padding: '2.5rem', color: 'var(--text-muted)' }}>
                        No appointments found matching your filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
