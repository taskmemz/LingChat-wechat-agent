CAPABILITIES = [
    # ========== 消息 ==========
    {
        "name": "wechat_send_message",
        "description": "给微信好友或群聊发送文本消息。支持 @ 群成员和 @所有人。每条消息不超过2000字。",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "好友备注名或群聊名称，必须是微信中的准确名称",
                },
                "content": {"type": "string", "description": "消息内容"},
                "at_members": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "群聊中需要 @ 的成员昵称列表",
                },
                "at_all": {
                    "type": "boolean",
                    "description": "是否 @ 所有人（仅群主/管理员可用）",
                },
            },
            "required": ["target", "content"],
        },
        "authorization": "confirm",
    },
    {
        "name": "wechat_send_messages",
        "description": "发送多条文本消息给好友或群聊。用于需要分开发送多条消息的场景。",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "好友备注名或群聊名称"},
                "messages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "多条消息内容列表，每条不超过2000字",
                },
            },
            "required": ["target", "messages"],
        },
        "authorization": "confirm",
    },
    {
        "name": "wechat_send_files",
        "description": "给微信好友或群聊发送文件。支持各种类型文件，单文件最大 1GB。",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "好友备注名或群聊名称"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "待发送文件的本地绝对路径列表",
                },
            },
            "required": ["target", "files"],
        },
        "authorization": "confirm",
    },
    # ========== 好友信息 ==========
    {
        "name": "wechat_get_my_info",
        "description": "获取当前登录微信的个人信息，包括昵称、微信号、wxid 等。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "authorization": "auto",
    },
    {
        "name": "wechat_get_friends",
        "description": "获取所有微信好友的详细信息列表，包括昵称、微信号、地区、备注、标签等。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "authorization": "auto",
    },
    {
        "name": "wechat_get_friend_profile",
        "description": "获取单个好友的详细资料，包括昵称、微信号、地区、备注、个性签名、来源等。",
        "parameters": {
            "type": "object",
            "properties": {
                "friend": {
                    "type": "string",
                    "description": "好友备注名",
                },
            },
            "required": ["friend"],
        },
        "authorization": "auto",
    },
    {
        "name": "wechat_get_groups",
        "description": "获取所有已加入的群聊名称列表。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "authorization": "auto",
    },
    {
        "name": "wechat_get_group_members",
        "description": "获取指定群聊内的所有成员名称。",
        "parameters": {
            "type": "object",
            "properties": {
                "group": {"type": "string", "description": "群聊名称"},
            },
            "required": ["group"],
        },
        "authorization": "auto",
    },
    {
        "name": "wechat_get_common_groups",
        "description": "获取你和某个好友的共同群聊名称列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "friend": {"type": "string", "description": "好友备注名"},
            },
            "required": ["friend"],
        },
        "authorization": "auto",
    },
    # ========== 朋友圈 ==========
    {
        "name": "wechat_post_moments",
        "description": "发布微信朋友圈。支持文字和图片/视频。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "朋友圈文字内容"},
                "medias": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "图片或视频文件的本地绝对路径列表",
                },
            },
        },
        "authorization": "auto",
    },
    {
        "name": "wechat_get_moments",
        "description": "获取朋友圈内容。可以按时间范围（Today/Yesterday/Week/Month）筛选。",
        "parameters": {
            "type": "object",
            "properties": {
                "recent": {
                    "type": "string",
                    "enum": ["Today", "Yesterday", "Week", "Month"],
                    "description": "时间范围",
                },
            },
        },
        "authorization": "auto",
    },
    # ========== 好友设置 ==========
    {
        "name": "wechat_change_remark",
        "description": "修改好友的备注名、描述或电话号码。",
        "parameters": {
            "type": "object",
            "properties": {
                "friend": {"type": "string", "description": "好友当前备注名"},
                "remark": {"type": "string", "description": "新的备注名"},
                "description": {
                    "type": "string",
                    "description": "对好友的描述（可选）",
                },
                "phone": {
                    "type": "string",
                    "description": "电话号码（可选）",
                },
            },
            "required": ["friend", "remark"],
        },
        "authorization": "confirm",
    },
    {
        "name": "wechat_delete_friend",
        "description": "删除微信好友。",
        "parameters": {
            "type": "object",
            "properties": {
                "friend": {"type": "string", "description": "好友备注名"},
                "clear_chat": {
                    "type": "boolean",
                    "description": "是否同时清空聊天记录",
                },
            },
            "required": ["friend"],
        },
        "authorization": "confirm",
    },
    {
        "name": "wechat_add_friend",
        "description": "通过微信号或手机号添加新的微信好友。",
        "parameters": {
            "type": "object",
            "properties": {
                "number": {"type": "string", "description": "微信号或手机号"},
                "greetings": {
                    "type": "string",
                    "description": "添加好友时的招呼用语",
                },
                "remark": {"type": "string", "description": "备注名"},
            },
            "required": ["number"],
        },
        "authorization": "confirm",
    },
    # ========== 聊天记录 ==========
    {
        "name": "wechat_get_chat_history",
        "description": "获取与某个好友或群聊的聊天记录。可指定条数。",
        "parameters": {
            "type": "object",
            "properties": {
                "friend": {"type": "string", "description": "好友备注名或群聊名称"},
                "number": {
                    "type": "integer",
                    "description": "获取的聊天记录条数",
                },
            },
            "required": ["friend", "number"],
        },
        "authorization": "auto",
    },
]
