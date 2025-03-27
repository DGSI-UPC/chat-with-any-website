document.addEventListener('DOMContentLoaded', () => {
    const urlInput = document.getElementById('url-input');
    const addKnowledgeBtn = document.getElementById('add-knowledge-btn');
    const knowledgeStatus = document.getElementById('knowledge-status');

    const chatInput = document.getElementById('chat-input');
    const sendChatBtn = document.getElementById('send-chat-btn');
    const chatHistory = document.getElementById('chat-history');
    const chatStatus = document.getElementById('chat-status');

    const API_BASE_URL = '/api'; // Relative URL since frontend is served by FastAPI

    // --- Helper Functions ---

    function addMessageToChat(role, text, sources = []) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', role);

        // Sanitize text before inserting (basic protection)
        const textNode = document.createElement('span');
        textNode.textContent = text;
        messageDiv.appendChild(textNode);

         // Display sources if available (for assistant messages)
        if (role === 'assistant' && sources.length > 0) {
             const sourcesList = document.createElement('ul');
             sourcesList.style.fontSize = '0.8em';
             sourcesList.style.marginTop = '0.5em';
             sourcesList.style.listStyleType = 'disc';
             sourcesList.style.marginLeft = '20px';
             sourcesList.innerHTML = '<strong>Sources:</strong>';
             sources.forEach(source => {
                 const li = document.createElement('li');
                 const a = document.createElement('a');
                 a.href = source;
                 a.textContent = source;
                 a.target = '_blank'; // Open in new tab
                 a.rel = 'noopener noreferrer';
                 li.appendChild(a);
                 sourcesList.appendChild(li);
             });
             messageDiv.appendChild(sourcesList);
         }


        chatHistory.appendChild(messageDiv);
        // Scroll to the bottom
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

     function setStatus(element, message, isError = false, isLoading = false) {
         element.textContent = message;
         element.style.color = isError ? '#a94442' : '#555'; // Red for errors
         if (isLoading) {
             element.classList.add('loading');
         } else {
             element.classList.remove('loading');
         }
     }

    // --- Knowledge Addition ---

    addKnowledgeBtn.addEventListener('click', handleAddKnowledge);
    urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            handleAddKnowledge();
        }
    });

    async function handleAddKnowledge() {
        const url = urlInput.value.trim();
        if (!url) {
            setStatus(knowledgeStatus, 'Please enter a valid URL.', true);
            return;
        }

        // Basic URL validation (more robust validation is complex)
        try {
             new URL(url);
        } catch (_) {
             setStatus(knowledgeStatus, 'Invalid URL format.', true);
             return;
        }


        setStatus(knowledgeStatus, `Requesting to add ${url}...`, false, true);
        addKnowledgeBtn.disabled = true;
        urlInput.disabled = true;

        try {
            const response = await fetch(`${API_BASE_URL}/add_knowledge`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url: url }),
            });

            const result = await response.json();

            if (!response.ok) {
                // Try to get detail from FastAPI error response
                const errorDetail = result.detail || `HTTP error! status: ${response.status}`;
                throw new Error(errorDetail);
            }

            setStatus(knowledgeStatus, result.message || 'Request accepted. Processing in background.');
            urlInput.value = ''; // Clear input on success

        } catch (error) {
            console.error('Error adding knowledge:', error);
            setStatus(knowledgeStatus, `Error: ${error.message}`, true);
        } finally {
            addKnowledgeBtn.disabled = false;
            urlInput.disabled = false;
            // Status message remains until next action
        }
    }

    // --- Chat Interaction ---

    sendChatBtn.addEventListener('click', handleSendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { // Send on Enter, allow Shift+Enter for newline
             e.preventDefault(); // Prevent default newline in input
            handleSendMessage();
        }
    });

    async function handleSendMessage() {
        const question = chatInput.value.trim();
        if (!question) return;

        addMessageToChat('user', question);
        chatInput.value = ''; // Clear input immediately
        setStatus(chatStatus, 'Thinking...', false, true);
        sendChatBtn.disabled = true;
        chatInput.disabled = true;

        try {
            const response = await fetch(`${API_BASE_URL}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                // Add session_id if you implement multi-user sessions
                body: JSON.stringify({ question: question /*, session_id: 'some_session' */}),
            });

            const result = await response.json();

            if (!response.ok) {
                 const errorDetail = result.detail || `HTTP error! status: ${response.status}`;
                throw new Error(errorDetail);
            }

            addMessageToChat('assistant', result.answer, result.sources);
            setStatus(chatStatus, ''); // Clear status

        } catch (error) {
            console.error('Error sending message:', error);
            addMessageToChat('error', `Sorry, I encountered an error: ${error.message}`);
             setStatus(chatStatus, `Error: ${error.message}`, true);
        } finally {
             setStatus(chatStatus, '', false, false); // Clear loading status
            sendChatBtn.disabled = false;
            chatInput.disabled = false;
            chatInput.focus(); // Refocus input for next message
        }
    }

    // --- Load Initial Chat History ---
    async function loadChatHistory() {
        setStatus(chatStatus, 'Loading history...', false, true);
         try {
             // Add session_id parameter if needed
             const response = await fetch(`${API_BASE_URL}/chat_history?limit=50`); // Adjust limit
             if (!response.ok) {
                 const result = await response.json();
                 const errorDetail = result.detail || `HTTP error! status: ${response.status}`;
                 throw new Error(errorDetail);
             }
             const history = await response.json();
             chatHistory.innerHTML = ''; // Clear placeholder/previous history
             if (history.length === 0) {
                  addMessageToChat('system', 'No previous chat history found. Start chatting!');
             } else {
                  history.forEach(msg => addMessageToChat(msg.role, msg.content));
             }
             setStatus(chatStatus, ''); // Clear status

         } catch (error) {
             console.error('Error loading chat history:', error);
             // Keep the initial welcome message if history fails to load
             if (chatHistory.children.length <= 1) { // Check if only system message exists
                 addMessageToChat('error', `Could not load history: ${error.message}`);
             }
              setStatus(chatStatus, `Error loading history: ${error.message}`, true);
         } finally {
              setStatus(chatStatus, '', false, false); // Ensure loading indicator is removed
         }
     }

     // Initial load
     loadChatHistory();

});