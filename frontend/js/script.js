document.addEventListener('DOMContentLoaded', () => {
    const apiUrlBase = '/api/v1'; // Backend API prefix

    // --- DOM Elements ---
    const urlInput = document.getElementById('url-input');
    const scrapeButton = document.getElementById('scrape-button');
    const scrapeStatusDiv = document.getElementById('scrape-status');
    const sourcesListDiv = document.getElementById('sources-list');
    const chatListUl = document.getElementById('chat-list');
    const newChatButton = document.getElementById('new-chat-button');
    const deleteChatButton = document.getElementById('delete-chat-button');
    const chatWindow = document.getElementById('chat-window');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const currentChatTitle = document.getElementById('current-chat-title');
    const currentChatSourcesSpan = document.getElementById('current-chat-sources');


    // --- State Variables ---
    let currentChatId = null;
    let selectedSources = []; // URLs selected in the sidebar checkboxes
    let chatSources = []; // URLs associated with the currently loaded chat
    let pollingIntervalId = null; // For scrape status polling

    // --- API Functions ---
    const apiRequest = async (endpoint, method = 'GET', body = null) => {
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json',
            },
        };
        if (body) {
            options.body = JSON.stringify(body);
        }
        try {
            const response = await fetch(`${apiUrlBase}${endpoint}`, options);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                console.error(`API Error (${response.status}): ${errorData.detail}`);
                throw new Error(errorData.detail || `Request failed with status ${response.status}`);
            }
             // Handle 204 No Content
            if (response.status === 204) {
                return null;
            }
            return await response.json();
        } catch (error) {
            console.error('API Request failed:', error);
            // Display error to user?
            scrapeStatusDiv.textContent = `Error: ${error.message}`; // Show generic errors here?
            throw error; // Re-throw for calling function to handle if needed
        }
    };

    // --- Scraping ---
    const startScraping = async () => {
        const url = urlInput.value.trim();
        if (!url) {
            scrapeStatusDiv.textContent = 'Please enter a URL.';
            return;
        }

        // Basic URL validation (more robust needed)
        if (!url.startsWith('http://') && !url.startsWith('https://')) {
            scrapeStatusDiv.textContent = 'Please include http:// or https://';
            return;
        }

        scrapeButton.disabled = true;
        scrapeStatusDiv.textContent = `Requesting scrape for ${url}...`;

        try {
            const response = await apiRequest('/scrape', 'POST', { url });
            scrapeStatusDiv.textContent = `Scraping started for ${response.url}. Refreshing status...`;
            // Start polling for status
            startPollingStatus(response.url);
        } catch (error) {
            scrapeStatusDiv.textContent = `Error starting scrape: ${error.message}`;
            scrapeButton.disabled = false;
        }
    };

    const startPollingStatus = (scrapeUrl) => {
        if (pollingIntervalId) {
            clearInterval(pollingIntervalId); // Clear previous interval if any
        }

        // Extract domain/path part for the status check endpoint
        let urlForStatus;
        try {
            const parsed = new URL(scrapeUrl);
            urlForStatus = parsed.hostname + (parsed.pathname === '/' ? '' : parsed.pathname) + parsed.search + parsed.hash;
            // Remove trailing slash if present and path is not just '/'
            if (urlForStatus.endsWith('/') && urlForStatus.length > parsed.hostname.length + 1) {
                 urlForStatus = urlForStatus.slice(0, -1);
            }
        } catch (e) {
             console.error("Could not parse URL for status polling:", scrapeUrl);
             scrapeStatusDiv.textContent = "Error: Could not parse URL for status check.";
             scrapeButton.disabled = false;
             return;
        }


        pollingIntervalId = setInterval(async () => {
            try {
                console.log(`Polling status for: /scrape/status/${encodeURIComponent(urlForStatus)}`);
                const status = await apiRequest(`/scrape/status/${encodeURIComponent(urlForStatus)}`);
                scrapeStatusDiv.textContent = `Status (${status.url}): ${status.status} - Pages: ${status.progress}/${status.total_pages || '?'}. ${status.message || ''}`;

                if (status.status === 'completed' || status.status === 'failed' || status.status === 'completed_with_errors') {
                    clearInterval(pollingIntervalId);
                    pollingIntervalId = null;
                    scrapeButton.disabled = false;
                    // Refresh sources list after scraping finishes
                    loadAvailableSources();
                }
            } catch (error) {
                 // Stop polling on 404 (job not found) or other persistent errors
                 if (error.message.includes('404') || error.message.includes('Request failed')) {
                     console.error(`Error polling status, stopping polling: ${error.message}`);
                     scrapeStatusDiv.textContent = `Error checking status: ${error.message}. Stopped polling.`;
                     clearInterval(pollingIntervalId);
                     pollingIntervalId = null;
                     scrapeButton.disabled = false;
                 } else {
                    // Keep polling for transient errors maybe? Or stop anyway.
                     console.warn(`Temporary error polling status: ${error.message}. Retrying...`);
                     scrapeStatusDiv.textContent = `Error checking status: ${error.message}. Retrying...`;
                 }
            }
        }, 3000); // Poll every 3 seconds
    };

    // --- Sources ---
    const loadAvailableSources = async () => {
        sourcesListDiv.textContent = 'Loading sources...';
        try {
            const sources = await apiRequest('/sources');
            renderSources(sources);
        } catch (error) {
            sourcesListDiv.textContent = 'Failed to load sources.';
        }
    };

    const renderSources = (sources) => {
        sourcesListDiv.innerHTML = ''; // Clear previous list
        if (!sources || sources.length === 0) {
            sourcesListDiv.textContent = 'No websites scraped yet.';
            return;
        }
        sources.forEach(source => {
            const div = document.createElement('div');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `source-${source.url}`; // Ensure unique ID
            checkbox.value = source.url;
            checkbox.checked = selectedSources.includes(source.url); // Check if previously selected
             checkbox.addEventListener('change', handleSourceSelectionChange);

            const label = document.createElement('label');
            label.htmlFor = `source-${source.url}`;
            label.textContent = source.url;

            div.appendChild(checkbox);
            div.appendChild(label);
            sourcesListDiv.appendChild(div);
        });
         updateSelectedSourcesDisplay(); // Update display based on current selection
    };

     const handleSourceSelectionChange = () => {
        selectedSources = Array.from(sourcesListDiv.querySelectorAll('input[type="checkbox"]:checked'))
                               .map(cb => cb.value);
        console.log("Selected sources:", selectedSources);
        updateSelectedSourcesDisplay();
        // Important: Associate selected sources with the *current* chat context
        // This might require updating the chat state if a chat is active
        chatSources = [...selectedSources]; // Update chatSources when selection changes *while* a chat is active
        updateChatHeader(); // Reflect changes in the chat header immediately
    };

    const updateSelectedSourcesDisplay = () => {
         // This function updates the list of checkboxes based on `selectedSources` array.
         // It ensures consistency if sources are loaded/reloaded.
        const checkboxes = sourcesListDiv.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = selectedSources.includes(cb.value);
        });
         // Also update the display in the chat header if a chat is active
        updateChatHeader();
    }


    // --- Chat Management ---
    const loadChats = async () => {
        chatListUl.innerHTML = '<li>Loading chats...</li>';
        try {
            const chats = await apiRequest('/chats');
            renderChatList(chats);
        } catch (error) {
            chatListUl.innerHTML = '<li>Failed to load chats.</li>';
        }
    };

    const renderChatList = (chats) => {
        chatListUl.innerHTML = '';
        if (!chats || chats.length === 0) {
            chatListUl.innerHTML = '<li>No chats yet.</li>';
            return;
        }
        chats.forEach(chat => {
            const li = document.createElement('li');
            li.textContent = chat.first_message || `Chat (${chat.chat_id.substring(0, 6)}...)`;
            li.dataset.chatId = chat.chat_id;
            // Store associated sources with the list item
            li.dataset.sources = JSON.stringify(chat.selected_sources || []);
            li.addEventListener('click', () => loadChat(chat.chat_id));
            if (chat.chat_id === currentChatId) {
                li.classList.add('active');
            }
            chatListUl.appendChild(li);
        });
    };

    const loadChat = async (chatId) => {
        console.log(`Loading chat: ${chatId}`);
        if (currentChatId === chatId) return; // Don't reload if already active

        try {
            const chatHistory = await apiRequest(`/chats/${chatId}`);
            currentChatId = chatId;
            chatWindow.innerHTML = ''; // Clear previous chat content
            chatHistory.history.forEach(addMessageToChat);

            // Set the associated sources for this loaded chat
            chatSources = chatHistory.selected_sources || [];
            selectedSources = [...chatSources]; // Update sidebar selection to match loaded chat
            updateSelectedSourcesDisplay(); // Reflect this in the sidebar checkboxes

            updateChatHeader(); // Update title and sources display
            highlightActiveChat();
            deleteChatButton.style.display = 'inline-block'; // Show delete button
             // Scroll to bottom after loading history
             chatWindow.scrollTop = chatWindow.scrollHeight;

        } catch (error) {
            console.error(`Failed to load chat ${chatId}:`, error);
            // Maybe display an error message to the user
        }
    };

    const startNewChat = () => {
        currentChatId = null; // Indicate a new chat (ID will be assigned on first message)
        chatWindow.innerHTML = ''; // Clear chat window
        chatSources = [...selectedSources]; // A new chat starts with currently selected sources
        updateChatHeader();
        highlightActiveChat();
        deleteChatButton.style.display = 'none'; // Hide delete button for new chats
        messageInput.focus();
         // Keep current source selection in the sidebar
        // selectedSources = []; // Optionally reset source selection for new chat? Let's keep it.
        // updateSelectedSourcesDisplay();
        console.log("Started new chat session.");
    };

    const deleteCurrentChat = async () => {
        if (!currentChatId) return;

        if (confirm(`Are you sure you want to delete chat "${currentChatTitle.textContent}"?`)) {
            try {
                await apiRequest(`/chats/${currentChatId}`, 'DELETE');
                console.log(`Chat ${currentChatId} deleted.`);
                startNewChat(); // Go back to a new chat state
                loadChats(); // Refresh chat list
            } catch (error) {
                console.error(`Failed to delete chat ${currentChatId}:`, error);
                alert(`Error deleting chat: ${error.message}`);
            }
        }
    };

    const updateChatHeader = () => {
         if (currentChatId) {
             // Try to find the chat title from the list item
             const activeLi = chatListUl.querySelector(`li[data-chat-id="${currentChatId}"]`);
             currentChatTitle.textContent = activeLi ? activeLi.textContent : `Chat (${currentChatId.substring(0, 6)}...)`;
         } else {
             currentChatTitle.textContent = "New Chat";
         }
         currentChatSourcesSpan.textContent = chatSources.length > 0 ? chatSources.join(', ') : 'None selected';
         currentChatSourcesSpan.title = chatSources.join(', '); // Tooltip for long lists
         deleteChatButton.style.display = currentChatId ? 'inline-block' : 'none';
     };


    const highlightActiveChat = () => {
        const items = chatListUl.querySelectorAll('li');
        items.forEach(item => {
            if (item.dataset.chatId === currentChatId) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
    };


    // --- Chat Interaction ---
    const sendMessage = async () => {
        const query = messageInput.value.trim();
        if (!query) return;

         // Use the sources associated with the chat OR the currently selected ones for a new chat
        const sourcesForRequest = currentChatId ? chatSources : selectedSources;

        if (sourcesForRequest.length === 0) {
             alert("Please select at least one source website for the chat.");
             return;
        }


        // Display user message immediately
        addMessageToChat({ role: 'user', content: query });
        messageInput.value = ''; // Clear input
        messageInput.disabled = true;
        sendButton.disabled = true;
        addTypingIndicator();

        try {
            const requestBody = {
                chat_id: currentChatId, // Will be null for the first message of a new chat
                query: query,
                selected_sources: sourcesForRequest
            };
            console.log("Sending request:", requestBody);

            const response = await apiRequest('/ask', 'POST', requestBody);

            removeTypingIndicator();

            // If it was a new chat, store the returned ID and reload chat list
            if (!currentChatId) {
                currentChatId = response.chat_id;
                chatSources = [...sourcesForRequest]; // Lock sources for this new chat
                updateChatHeader();
                deleteChatButton.style.display = 'inline-block';
                loadChats(); // Reload list to show the new chat
            }

            // Add assistant message
            addMessageToChat(response.response); // response.response is the ChatMessage object

        } catch (error) {
            removeTypingIndicator();
            addMessageToChat({ role: 'assistant', content: `Error: ${error.message}` });
        } finally {
            messageInput.disabled = false;
            sendButton.disabled = false;
            messageInput.focus();
        }
    };

    const addMessageToChat = (message) => {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', message.role); // 'user' or 'assistant'

        const roleSpan = document.createElement('div');
        roleSpan.classList.add('role');
        roleSpan.textContent = message.role === 'user' ? 'You' : 'Assistant';

        const contentDiv = document.createElement('div');
        contentDiv.classList.add('content');
         // Basic check for potential HTML - render as text
         // For more safety, use a sanitizer library if LLM might return HTML
        contentDiv.textContent = message.content;

        messageDiv.appendChild(roleSpan);
        messageDiv.appendChild(contentDiv);

        // Add sources if available (for assistant messages)
        if (message.role === 'assistant' && message.sources && message.sources.length > 0) {
            const sourcesDiv = document.createElement('div');
            sourcesDiv.classList.add('sources');
            sourcesDiv.innerHTML = '<strong>Sources:</strong> ';
            message.sources.forEach((sourceUrl, index) => {
                const link = document.createElement('a');
                link.href = sourceUrl;
                link.target = '_blank'; // Open in new tab
                link.textContent = `[${index + 1}]`;
                link.title = sourceUrl;
                sourcesDiv.appendChild(link);
            });
            messageDiv.appendChild(sourcesDiv);
        }

        chatWindow.appendChild(messageDiv);
        // Scroll to bottom
        chatWindow.scrollTop = chatWindow.scrollHeight;
    };

    const addTypingIndicator = () => {
        const typingDiv = document.createElement('div');
        typingDiv.classList.add('message', 'assistant', 'typing-indicator');
        typingDiv.id = 'typing-indicator';
        typingDiv.textContent = 'Assistant is typing...';
        chatWindow.appendChild(typingDiv);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    };

    const removeTypingIndicator = () => {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) {
            indicator.remove();
        }
    };


    // --- Event Listeners ---
    scrapeButton.addEventListener('click', startScraping);
    urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            startScraping();
        }
    });

    sendButton.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', (e) => {
        // Allow sending with Shift+Enter, new line with Enter
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault(); // Prevent default newline behavior
            sendMessage();
        }
    });

    newChatButton.addEventListener('click', startNewChat);
    deleteChatButton.addEventListener('click', deleteCurrentChat);


    // --- Initial Load ---
    const initializeApp = () => {
        console.log("Initializing application...");
        loadAvailableSources();
        loadChats();
        startNewChat(); // Start with a blank new chat
    };

    initializeApp();
});