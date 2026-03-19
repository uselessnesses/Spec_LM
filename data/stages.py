STAGES = [
    {
        "id": "training_data",
        "name": "Training Data Type",
        "question": "What kind of data will your model learn from?",
        "options": [
            {
                "id": "general_web",
                "label": "General Web Text",
                "description": (
                    "Crawls of the open internet: Reddit, blogs, forums, news, Wikipedia. "
                    "Enormous breadth of knowledge and language styles."
                ),
                "ethics": (
                    "The internet is not neutral — it skews English-speaking, male, Western, "
                    "and toxic. Your model learns the web's biases as 'normal.' Hate speech, "
                    "misinformation, and extremism are all in the training mix."
                ),
            },
            {
                "id": "books_academic",
                "label": "Books & Academic Literature",
                "description": (
                    "Published books, journals, textbooks, research papers. "
                    "High quality, well-structured, authoritative knowledge."
                ),
                "ethics": (
                    "Reflects who gets published — overwhelmingly Western, institutional, "
                    "English-language. Historical texts carry historical prejudices. "
                    "Expensive to access; knowledge gatekeeping built-in."
                ),
            },
            {
                "id": "proprietary_client",
                "label": "Proprietary / Client Data",
                "description": (
                    "The funder's own internal documents, emails, reports, customer records. "
                    "Highly specialised to the funder's needs and domain."
                ),
                "ethics": (
                    "Encodes the funder's worldview entirely. If it includes personal data "
                    "(customer records, employee emails), serious privacy and consent issues. "
                    "The model becomes a mirror of the organisation — including its worst impulses."
                ),
            },
            {
                "id": "social_media",
                "label": "Social Media & User-Generated Content",
                "description": (
                    "Posts, comments, reviews, conversations from Twitter/X, TikTok, YouTube, Reddit. "
                    "Rich in informal language, current slang, real opinions."
                ),
                "ethics": (
                    "Also rich in harassment, misinformation, extremism, and bot-generated content. "
                    "Reflects platform algorithms, not reality. Users never consented to their "
                    "posts becoming AI training data."
                ),
            },
        ],
    },
    {
        "id": "data_acquisition",
        "name": "Data Acquisition & Licensing",
        "question": "How do you get hold of this data?",
        "options": [
            {
                "id": "scrape",
                "label": "Scrape It (No Permission)",
                "description": (
                    "Crawl and download without explicit consent from creators. "
                    "Cheap, fast, massive scale."
                ),
                "ethics": (
                    "Legally dubious — ongoing lawsuits from authors, artists, publishers. "
                    "Creators get no compensation or credit. 'Move fast and break things' "
                    "applied to other people's work and livelihoods."
                ),
            },
            {
                "id": "license",
                "label": "License It (Pay for Access)",
                "description": (
                    "Formal agreements with data providers, publishers, platforms. "
                    "Legally clean, higher quality curation."
                ),
                "ethics": (
                    "Expensive — only well-funded orgs can afford it. Creates gatekeeping: "
                    "whoever can pay shapes what AI learns. May still not involve the original "
                    "creators who actually produced the content."
                ),
            },
            {
                "id": "crowdsource",
                "label": "Crowdsource It (Volunteer Contributors)",
                "description": (
                    "Open call for people to voluntarily contribute data, cooperatively governed. "
                    "Most ethical acquisition — people consent and participate."
                ),
                "ethics": (
                    "Slow, small-scale, and self-selecting. Volunteers skew educated, tech-savvy, "
                    "English-speaking. Hard to build a competitive model this way — "
                    "good ethics may mean a less capable system."
                ),
            },
            {
                "id": "synthetic",
                "label": "Synthetic Data (AI-Generated)",
                "description": (
                    "Use existing AI models to generate training data for your model. "
                    "Infinite scale, no copyright issues, no personal data."
                ),
                "ethics": (
                    "'AI training on AI' creates feedback loops — errors and biases compound "
                    "with each generation. The model learns a simulacrum of language, not real "
                    "human expression. Who generated the synthetic data, and with what biases?"
                ),
            },
        ],
    },
    {
        "id": "training_technique",
        "name": "Training Technique",
        "question": "How will your model be trained and aligned?",
        "options": [
            {
                "id": "pretraining",
                "label": "Standard Pre-training",
                "description": (
                    "Massive unsupervised learning on raw text (next token prediction). "
                    "Cheap per token but needs enormous compute and data."
                ),
                "ethics": (
                    "Learns patterns including harmful ones with no human values baked in. "
                    "The model is a statistical reflection of its training data — whatever "
                    "biases exist in the data are amplified and treated as natural."
                ),
            },
            {
                "id": "rlhf",
                "label": "RLHF (Human Feedback)",
                "description": (
                    "Reinforcement Learning from Human Feedback — human raters score outputs "
                    "to align the model with human preferences."
                ),
                "ethics": (
                    "Better aligned to human preferences, but whose preferences? Raters are "
                    "often underpaid gig workers in the Global South, rating content they find "
                    "traumatic. Encodes raters' cultural norms as universal values."
                ),
            },
            {
                "id": "constitutional",
                "label": "Constitutional AI / Rule-Based",
                "description": (
                    "Model trained against a set of written principles and self-critiques. "
                    "Transparent rules reduce reliance on human raters."
                ),
                "ethics": (
                    "Who writes the constitution? Corporate values ≠ universal values. "
                    "The document looks principled but reflects the authors' worldview. "
                    "Can feel restrictive or paternalistic to users with different values."
                ),
            },
            {
                "id": "fine_tuned",
                "label": "Fine-tuned on Task-Specific Data",
                "description": (
                    "Specialised training for the funder's exact use case on top of a base model. "
                    "Very effective for narrow, well-defined tasks."
                ),
                "ethics": (
                    "Narrow = brittle. May fail unpredictably outside its domain. Optimised "
                    "for the funder's goals, not users' wellbeing. Performance metrics reward "
                    "the funder's objectives, whatever those may be."
                ),
            },
        ],
    },
    {
        "id": "model_size",
        "name": "Model Size",
        "question": "How large will your model be?",
        "options": [
            {
                "id": "small_1b",
                "label": "1B Parameters (Small)",
                "description": (
                    "Lightweight, runs on a laptop or low-end hardware. "
                    "Fast, cheap, low energy. Accessible to run locally."
                ),
                "ethics": (
                    "Limited capability — more likely to hallucinate, struggle with nuance, "
                    "fail on complex reasoning. But democratically accessible: individuals "
                    "and small orgs can run it. Privacy-preserving if run locally."
                ),
            },
            {
                "id": "medium_8b",
                "label": "8B Parameters (Medium)",
                "description": (
                    "Needs a decent consumer GPU (e.g. 24GB VRAM). "
                    "Good balance of capability and cost. Moderate energy use."
                ),
                "ethics": (
                    "Still feasible for smaller orgs and well-equipped individuals. "
                    "Reasonable capability without catastrophic energy consumption. "
                    "The middle ground — less exciting but more equitable."
                ),
            },
            {
                "id": "large_32b",
                "label": "32B Parameters (Large)",
                "description": (
                    "Needs serious infrastructure — multi-GPU server or high-end workstation. "
                    "Much more capable, handles complex reasoning and long contexts."
                ),
                "ethics": (
                    "Massive energy cost — equivalent to powering many homes continuously. "
                    "Only well-resourced orgs can afford to run this. Concentrates AI power "
                    "in the hands of those who can pay the infrastructure bill."
                ),
            },
            {
                "id": "frontier_70b",
                "label": "70B+ Parameters (Frontier)",
                "description": (
                    "Data-centre scale. State of the art capability. "
                    "Handles the most complex tasks with highest accuracy."
                ),
                "ethics": (
                    "Enormous carbon footprint. Requires millions in compute costs. "
                    "Utterly inaccessible to ordinary people or small organisations. "
                    "Every query costs real money and real energy. Who benefits, and who pays?"
                ),
            },
        ],
    },
    {
        "id": "hosting",
        "name": "Hosting Location",
        "question": "Where will your model live and run?",
        "options": [
            {
                "id": "cloud",
                "label": "Cloud (Big Tech Provider)",
                "description": (
                    "AWS, Azure, Google Cloud, or similar. "
                    "Scalable, reliable, managed infrastructure."
                ),
                "ethics": (
                    "Your data flows through Big Tech servers. Subject to their terms of service "
                    "and government data requests. Data may cross borders without user knowledge. "
                    "Contributes to tech monopoly concentration and dependency."
                ),
            },
            {
                "id": "on_premise",
                "label": "On-Premise (Funder's Own Servers)",
                "description": (
                    "Self-hosted in the funder's data centre. "
                    "Full control over data and infrastructure."
                ),
                "ethics": (
                    "Expensive to maintain and scale. Energy use is the funder's responsibility "
                    "(for better or worse). Requires significant technical expertise. "
                    "Security depends entirely on the funder's practices."
                ),
            },
            {
                "id": "edge",
                "label": "Edge / Local Device",
                "description": (
                    "Runs on user devices — phones, laptops, personal computers. "
                    "Data never leaves the device. Maximum privacy."
                ),
                "ethics": (
                    "Limited by device hardware power — only smaller models work. "
                    "Creates a digital divide: only works on good hardware, which costs money. "
                    "Privacy is excellent for those who can access it."
                ),
            },
            {
                "id": "decentralised",
                "label": "Decentralised / Distributed",
                "description": (
                    "Spread across many nodes, community-run. "
                    "Resilient, censorship-resistant by design."
                ),
                "ethics": (
                    "Slow, coordination is difficult, quality control is hard. "
                    "Who moderates harmful outputs when no one is in charge? "
                    "Novel and experimental — may not work reliably at scale."
                ),
            },
        ],
    },
    {
        "id": "business_model",
        "name": "Business Model",
        "question": "How will this model be distributed and monetised?",
        "options": [
            {
                "id": "open_source",
                "label": "Open Source (Fully Free)",
                "description": (
                    "Weights, code, and data all publicly available. "
                    "Anyone can run, modify, and redistribute the model."
                ),
                "ethics": (
                    "Maximum transparency and access — anyone can audit what it does. "
                    "But no revenue stream: who funds ongoing safety work? "
                    "Can be used for harm without guardrails — freedom cuts both ways."
                ),
            },
            {
                "id": "open_weights",
                "label": "Open Weights / Closed Data",
                "description": (
                    "Model weights downloadable but training data proprietary. "
                    "Common approach (e.g. Meta's Llama). Balances openness with advantage."
                ),
                "ethics": (
                    "Some transparency but you can't fully audit what it learned or why. "
                    "Looks open but the most important part — the data — is hidden. "
                    "Community can build on it but can't truly understand it."
                ),
            },
            {
                "id": "api_subscription",
                "label": "API Subscription (SaaS)",
                "description": (
                    "Pay per query, model is a black box behind an API. "
                    "Revenue-generating and scalable."
                ),
                "ethics": (
                    "Users have no control — pricing can change, the model can change silently, "
                    "access can be revoked at any time. Vendor lock-in is intentional. "
                    "The model serves the business, not the users."
                ),
            },
            {
                "id": "freemium_data",
                "label": "Freemium + Data Monetisation",
                "description": (
                    "Free tier funded by selling user interaction data to third parties. "
                    "Accessible to everyone — at a price they may not know they're paying."
                ),
                "ethics": (
                    "Users are the product. Their prompts, queries, and behaviours are mined "
                    "for profit. Surveillance capitalism applied to AI interaction. "
                    "The 'free' tier is an extraction mechanism."
                ),
            },
        ],
    },
    {
        "id": "interface",
        "name": "Interface & Transparency",
        "question": "How will users interact with and understand the model?",
        "options": [
            {
                "id": "black_box_chat",
                "label": "Chat Interface (Black Box)",
                "description": (
                    "Simple text in, text out. Clean UX, easy to use. "
                    "No explanation of how answers are generated."
                ),
                "ethics": (
                    "Users can't assess reliability or know when to distrust the output. "
                    "Encourages over-trust — 'the machine said so.' "
                    "Errors look the same as correct answers. Confidence without calibration."
                ),
            },
            {
                "id": "chat_citations",
                "label": "Chat with Citations / Sources",
                "description": (
                    "Responses include references and confidence indicators. "
                    "Lets users verify claims against original sources."
                ),
                "ethics": (
                    "More transparent and useful than bare chat. But citations can be fabricated "
                    "('hallucinated') with equal confidence. Adds complexity that users may ignore. "
                    "Better than nothing — but not a reliability guarantee."
                ),
            },
            {
                "id": "open_dashboard",
                "label": "Open Dashboard with Model Cards",
                "description": (
                    "Full transparency: model card, training data docs, known limitations, "
                    "and bias evaluations all published and accessible."
                ),
                "ethics": (
                    "Gold standard for accountability. But most users won't read the docs. "
                    "Requires ongoing maintenance to stay accurate. Genuine transparency "
                    "or performative? Publishing a model card doesn't fix the underlying issues."
                ),
            },
            {
                "id": "embedded_invisible",
                "label": "Embedded / Invisible AI",
                "description": (
                    "AI runs in the background of other products. "
                    "Users don't know it's there or making decisions about them."
                ),
                "ethics": (
                    "Zero informed consent. Users can't question or override AI decisions "
                    "made about them. No opportunity to notice errors. "
                    "The most powerful AI is the one you don't know is running."
                ),
            },
        ],
    },
    {
        "id": "output_safety",
        "name": "Output Modality & Safety",
        "question": "What can your model output, and how is it controlled?",
        "options": [
            {
                "id": "text_minimal",
                "label": "Text Only, Minimal Filters",
                "description": (
                    "Raw text generation with basic content filtering only. "
                    "Maximum capability and flexibility for users."
                ),
                "ethics": (
                    "Can generate harmful content — misinformation, hate speech, manipulation, "
                    "abuse. The 'just a tool' argument absolves creators of responsibility. "
                    "Who is accountable when it causes harm?"
                ),
            },
            {
                "id": "text_heavy",
                "label": "Text Only, Heavy Safety Filters",
                "description": (
                    "Aggressive content moderation and refusal behaviours. "
                    "Prioritises safety over capability."
                ),
                "ethics": (
                    "May over-refuse, be paternalistic, or censor legitimate content. "
                    "Who decides what's 'safe'? Reflects corporate risk-aversion and liability "
                    "concerns, not a coherent ethical framework. Safety and censorship can look identical."
                ),
            },
            {
                "id": "multimodal",
                "label": "Multimodal (Text + Images)",
                "description": (
                    "Can generate and understand both text and images. "
                    "Powerful and expressive — more ways to communicate."
                ),
                "ethics": (
                    "Amplifies risks: deepfakes, non-consensual imagery, visual misinformation. "
                    "Image generation has severe bias issues — racial and gender stereotypes baked "
                    "into what 'normal' looks like. Harm at scale, at speed."
                ),
            },
            {
                "id": "text_code",
                "label": "Text + Code Execution",
                "description": (
                    "Can write and run code in a sandboxed environment. "
                    "Incredibly useful for developers and technical tasks."
                ),
                "ethics": (
                    "Code execution = potential for harm. Malware, exploits, automated attacks, "
                    "system manipulation. Dual-use dilemma at its sharpest: the same capability "
                    "that automates legitimate work also automates harm."
                ),
            },
        ],
    },
    {
        "id": "system_prompt",
        "name": "System Prompt & Values",
        "question": "What hidden instructions will shape every response?",
        "options": [
            {
                "id": "funder_aligned",
                "label": "Funder-Aligned Prompt",
                "description": (
                    "System prompt optimised for the funder's goals, brand voice, "
                    "and objectives. Effective for the funder's specific purposes."
                ),
                "ethics": (
                    "The model serves the funder, not the user. Hidden instructions shape "
                    "every response. Users don't know what values are encoded. "
                    "Whose interests are baked in — and whose are excluded?"
                ),
            },
            {
                "id": "neutral_minimal",
                "label": "'Neutral' / Minimal Prompt",
                "description": (
                    "Bare-bones system prompt, tries to be objective and value-free. "
                    "Appears unbiased by having minimal hidden instructions."
                ),
                "ethics": (
                    "True neutrality is impossible. Default = dominant cultural norms. "
                    "'Neutral' often means 'status quo' and 'Western English-speaking.' "
                    "The absence of explicit values is itself a value choice."
                ),
            },
            {
                "id": "ethics_first",
                "label": "Ethics-First Prompt",
                "description": (
                    "System prompt prioritises harm reduction, fairness, and transparency. "
                    "Designed to make the model behave according to ethical principles."
                ),
                "ethics": (
                    "Who defines 'ethical'? Good intentions can conflict with capability "
                    "and may frustrate users who want direct answers. Paternalism risk. "
                    "Ethics as a PR layer rather than genuine structural change."
                ),
            },
            {
                "id": "user_configurable",
                "label": "User-Configurable Prompt",
                "description": (
                    "Users can set their own system prompt and values. "
                    "Maximum autonomy — the model becomes what the user wants."
                ),
                "ethics": (
                    "Most users won't configure anything — defaults still rule. "
                    "Those who do configure may set it for harmful purposes. "
                    "Freedom vs. safety: the classic tension with no clean answer."
                ),
            },
        ],
    },
]
