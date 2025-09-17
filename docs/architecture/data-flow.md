# kbxy-monsters-pro 数据流设计

## 系统数据流总览

```mermaid
graph TB
    subgraph "数据源层 Data Sources"
        ExtAPI[4399网站API]
        UserInput[用户输入数据]
        FileUpload[文件上传]
        AIModel[AI模型处理]
    end
    
    subgraph "数据获取层 Data Acquisition"
        Crawler[crawler_service<br/>网络爬虫]
        Parser[HTML/JSON解析器]
        Validator[数据验证器]
        Normalizer[normalization<br/>数据标准化]
    end
    
    subgraph "业务处理层 Business Processing"
        MonstersLogic[monsters_service<br/>妖怪业务逻辑]
        SkillsLogic[skills_service<br/>技能管理]
        TagsLogic[tags_service<br/>标签识别]
        DeriveLogic[derive_service<br/>派生计算]
        ImageLogic[image_service<br/>图片处理]
        CollectionLogic[collection_service<br/>收藏管理]
    end
    
    subgraph "数据存储层 Data Storage"
        SQLiteDB[(SQLite数据库)]
        FileSystem[本地文件系统]
        Cache[应用缓存]
    end
    
    subgraph "数据输出层 Data Output"
        RestAPI[REST API响应]
        JSONResponse[JSON数据格式]
        FileExport[文件导出]
        ImageURL[图片URL]
    end
    
    subgraph "客户端层 Client Layer"
        ReactApp[React应用]
        Browser[浏览器渲染]
        UserUI[用户界面]
    end
    
    %% 数据流向
    ExtAPI --> Crawler
    UserInput --> Parser
    FileUpload --> Validator
    
    Crawler --> Parser
    Parser --> Validator
    Validator --> Normalizer
    
    Normalizer --> MonstersLogic
    Normalizer --> SkillsLogic
    Normalizer --> TagsLogic
    
    MonstersLogic --> DeriveLogic
    TagsLogic --> DeriveLogic
    
    FileUpload --> ImageLogic
    ImageLogic --> AIModel
    AIModel --> ImageLogic
    
    MonstersLogic --> SQLiteDB
    SkillsLogic --> SQLiteDB
    TagsLogic --> SQLiteDB
    DeriveLogic --> SQLiteDB
    CollectionLogic --> SQLiteDB
    ImageLogic --> FileSystem
    
    SQLiteDB --> RestAPI
    FileSystem --> ImageURL
    Cache --> RestAPI
    
    RestAPI --> JSONResponse
    ImageURL --> JSONResponse
    JSONResponse --> ReactApp
    
    ReactApp --> Browser
    Browser --> UserUI
    
    %% 反向数据流
    UserUI --> RestAPI
    RestAPI --> MonstersLogic
    RestAPI --> CollectionLogic
    
    %% 样式
    classDef sourceLayer fill:#fce4ec
    classDef acquireLayer fill:#e8f5e8
    classDef businessLayer fill:#fff3e0
    classDef storageLayer fill:#e3f2fd
    classDef outputLayer fill:#f3e5f5
    classDef clientLayer fill:#e1f5fe
    
    class ExtAPI,UserInput,FileUpload,AIModel sourceLayer
    class Crawler,Parser,Validator,Normalizer acquireLayer
    class MonstersLogic,SkillsLogic,TagsLogic,DeriveLogic,ImageLogic,CollectionLogic businessLayer
    class SQLiteDB,FileSystem,Cache storageLayer
    class RestAPI,JSONResponse,FileExport,ImageURL outputLayer
    class ReactApp,Browser,UserUI clientLayer
```

## 核心数据流程详解

### 1. 数据获取与入库流程

```mermaid
graph TD
    subgraph "爬虫数据流程"
        A[4399网站数据源] --> B[Kabu4399Crawler.crawl_all]
        B --> C[iter_detail_urls]
        C --> D[fetch_detail单个页面]
        D --> E[HTML解析提取数据]
        E --> F[MonsterRow/SkillRow对象]
    end
    
    subgraph "数据清洗流程"
        F --> G[数据格式验证]
        G --> H[normalization标准化]
        H --> I[去重检测]
        I --> J[关联关系处理]
    end
    
    subgraph "数据存储流程"
        J --> K[monsters_service.upsert]
        K --> L[Monster表插入/更新]
        L --> M[Skill表处理]
        M --> N[MonsterSkill关联]
        N --> O[Tag标签关联]
    end
    
    subgraph "派生计算流程"
        O --> P[derive_service.compute_and_persist]
        P --> Q[新五轴属性计算]
        Q --> R[MonsterDerived表存储]
    end
    
    %% 样式
    classDef crawlerFlow fill:#e8f5e8
    classDef cleanFlow fill:#fff3e0
    classDef storeFlow fill:#e3f2fd
    classDef deriveFlow fill:#f3e5f5
    
    class A,B,C,D,E,F crawlerFlow
    class G,H,I,J cleanFlow
    class K,L,M,N,O storeFlow
    class P,Q,R deriveFlow
```

### 2. 用户查询与展示流程

```mermaid
graph LR
    subgraph "用户交互"
        A[用户界面操作] --> B[React组件事件]
        B --> C[React Query请求]
    end
    
    subgraph "API处理"
        C --> D[FastAPI路由匹配]
        D --> E[参数验证解析]
        E --> F[业务服务调用]
    end
    
    subgraph "数据查询"
        F --> G[SQLAlchemy查询构建]
        G --> H[复杂WHERE条件]
        H --> I[JOIN关联查询]
        I --> J[排序分页处理]
        J --> K[SQLite执行查询]
    end
    
    subgraph "结果处理"
        K --> L[ORM对象转换]
        L --> M[Pydantic序列化]
        M --> N[JSON响应构建]
        N --> O[HTTP响应返回]
    end
    
    subgraph "前端渲染"
        O --> P[React Query缓存]
        P --> Q[组件状态更新]
        Q --> R[虚拟DOM渲染]
        R --> S[浏览器界面更新]
    end
```

### 3. 图片上传与AI处理流程

```mermaid
graph TB
    A[用户选择图片] --> B[前端文件验证]
    B --> C[FormData构建上传]
    C --> D[images.py路由接收]
    
    D --> E[image_service.处理]
    E --> F{文件格式检查}
    F -->|有效格式| G[文件名标准化]
    F -->|无效格式| H[返回错误响应]
    
    G --> I[本地文件存储]
    I --> J{需要AI处理?}
    J -->|是| K[Real-ESRGAN调用]
    J -->|否| L[直接使用原图]
    
    K --> M[AI超分辨率处理]
    M --> N[处理后图片保存]
    N --> O[多候选名称匹配]
    L --> O
    
    O --> P[图片索引更新]
    P --> Q[URL路径生成]
    Q --> R[返回访问链接]
    
    %% 错误处理分支
    H --> S[错误日志记录]
    S --> T[用户错误提示]
    
    %% 异常处理
    K -->|处理失败| U[回退到原图]
    U --> O
```

### 4. 标签智能识别流程

```mermaid
graph TD
    subgraph "标签识别触发"
        A[妖怪数据更新] --> B[自动标签检测]
        A1[用户手动请求] --> B
    end
    
    subgraph "正则表达式识别"
        B --> C[tags_service.suggest_tags_for_monster]
        C --> D[技能文本分析]
        D --> E[正则模式匹配]
        E --> F[buf_/deb_/util_分类]
    end
    
    subgraph "AI智能识别"
        C --> G[ai_suggest_tags_for_monster]
        G --> H[妖怪信息上下文构建]
        H --> I[AI模型推理]
        I --> J[标签候选生成]
    end
    
    subgraph "结果合并处理"
        F --> K[正则识别结果]
        J --> L[AI识别结果]
        K --> M[结果去重合并]
        L --> M
        M --> N[标签权重评分]
    end
    
    subgraph "标签应用"
        N --> O[用户确认/自动应用]
        O --> P[monsters_service.upsert_tags]
        P --> Q[Monster-Tag关联更新]
        Q --> R[派生属性重新计算]
    end
```

### 5. 派生属性计算流程

```mermaid
graph LR
    subgraph "输入数据收集"
        A[Monster基础六维] --> D[derive_service.compute_derived]
        B[Monster关联标签] --> D
        C[配置权重参数] --> D
    end
    
    subgraph "信号检测分析"
        D --> E[_detect_signals_v3]
        E --> F[29种战斗能力信号识别]
        F --> G[生存/抑制/资源信号分类]
    end
    
    subgraph "五轴属性计算"
        G --> H[体防轴计算]
        G --> I[体抗轴计算]
        G --> J[削防抗轴计算]
        G --> K[削攻法轴计算]
        G --> L[特殊战术轴计算]
    end
    
    subgraph "结果存储"
        H --> M[MonsterDerived对象]
        I --> M
        J --> M
        K --> M
        L --> M
        M --> N[数据库持久化]
        N --> O[API响应返回]
    end
```

### 6. 收藏夹管理流程

```mermaid
graph TB
    subgraph "收藏夹操作"
        A[用户收藏操作] --> B{操作类型}
        B -->|创建收藏夹| C[collections.py创建接口]
        B -->|添加成员| D[bulk_set_members接口]
        B -->|移除成员| E[bulk_set_members接口]
        B -->|查询收藏夹| F[列表查询接口]
    end
    
    subgraph "业务逻辑处理"
        C --> G[collection_service.get_or_create]
        D --> H[collection_service.bulk_set_members]
        E --> H
        F --> I[collection_service.list_collections]
    end
    
    subgraph "数据库操作"
        G --> J[Collection表插入]
        H --> K[CollectionItem关联操作]
        I --> L[分页查询执行]
        
        K --> M[批量添加/删除成员]
        M --> N[items_count计数更新]
    end
    
    subgraph "响应处理"
        J --> O[新收藏夹详情返回]
        N --> P[操作结果统计返回]
        L --> Q[收藏夹列表返回]
    end
```

## 数据一致性保证机制

### 1. 事务管理流程

```mermaid
graph LR
    A[数据库会话开始] --> B[FastAPI依赖注入]
    B --> C[业务逻辑执行]
    C --> D{操作成功?}
    D -->|是| E[自动提交事务]
    D -->|否| F[自动回滚事务]
    E --> G[会话关闭]
    F --> G
    G --> H[资源释放]
```

### 2. 数据验证流程

```mermaid
graph TB
    A[原始数据输入] --> B[Pydantic Schema验证]
    B --> C{格式验证通过?}
    C -->|否| D[ValidationError异常]
    C -->|是| E[业务规则验证]
    E --> F{业务验证通过?}
    F -->|否| G[HTTPException异常]
    F -->|是| H[数据库约束检查]
    H --> I{唯一性约束通过?}
    I -->|否| J[IntegrityError异常]
    I -->|是| K[数据成功存储]
```

### 3. 缓存同步流程

```mermaid
graph LR
    A[数据更新操作] --> B[数据库写入成功]
    B --> C[相关缓存失效]
    C --> D[React Query缓存更新]
    D --> E[前端状态同步]
    E --> F[UI界面刷新]
```

## 性能优化数据流

### 1. 查询优化流程

```mermaid
graph TB
    A[复杂查询请求] --> B[查询条件分析]
    B --> C{是否命中索引?}
    C -->|是| D[索引扫描执行]
    C -->|否| E[查询优化器介入]
    E --> F[JOIN顺序优化]
    F --> G[WHERE条件下推]
    G --> H[执行计划选择]
    H --> D
    D --> I[结果集返回]
    I --> J[分页截取]
    J --> K[预加载关联数据]
    K --> L[最终结果返回]
```

### 2. 批量处理优化

```mermaid
graph LR
    A[大批量数据] --> B[分批处理策略]
    B --> C[单批次数据]
    C --> D[批量SQL操作]
    D --> E[事务边界控制]
    E --> F[内存使用监控]
    F --> G{还有更多批次?}
    G -->|是| H[处理下一批]
    G -->|否| I[批量处理完成]
    H --> C
```

### 3. 图片处理优化

```mermaid
graph TB
    A[图片上传请求] --> B[文件大小检查]
    B --> C{是否需要压缩?}
    C -->|是| D[图片压缩处理]
    C -->|否| E[直接处理]
    D --> E
    E --> F{是否需要AI放大?}
    F -->|是| G[AI处理队列]
    F -->|否| H[直接存储]
    G --> I[异步AI处理]
    I --> J[处理结果通知]
    H --> K[图片URL返回]
    J --> K
```

## 数据安全流程

### 1. 输入安全验证

```mermaid
graph LR
    A[用户输入] --> B[XSS过滤]
    B --> C[SQL注入防护]
    C --> D[文件类型验证]
    D --> E[大小限制检查]
    E --> F[路径遍历防护]
    F --> G[安全的数据处理]
```

### 2. 数据备份流程

```mermaid
graph TB
    A[定时备份触发] --> B[数据库锁定]
    B --> C[SQLite文件复制]
    C --> D[备份文件压缩]
    D --> E[备份完整性验证]
    E --> F[旧备份清理]
    F --> G[备份完成通知]
```

### 3. 错误处理与恢复

```mermaid
graph LR
    A[系统异常] --> B[错误分类识别]
    B --> C{错误类型}
    C -->|数据库错误| D[事务回滚]
    C -->|网络错误| E[重试机制]
    C -->|业务错误| F[友好错误提示]
    D --> G[错误日志记录]
    E --> G
    F --> G
    G --> H[用户反馈显示]
```

## 数据格式规范

### API数据交换格式

```json
{
  "妖怪查询响应": {
    "items": [
      {
        "id": "integer",
        "name": "string",
        "element": "string",
        "role": "string",
        "hp": "float",
        "speed": "float",
        "attack": "float",
        "defense": "float",
        "magic": "float",
        "resist": "float",
        "possess": "boolean",
        "tags": ["string"],
        "skills": [
          {
            "id": "integer",
            "name": "string",
            "element": "string",
            "kind": "string",
            "power": "integer",
            "description": "string"
          }
        ],
        "derived": {
          "body_defense": "integer",
          "body_resist": "integer", 
          "debuff_def_res": "integer",
          "debuff_atk_mag": "integer",
          "special_tactics": "integer"
        },
        "image_url": "string|null"
      }
    ],
    "total": "integer",
    "page": "integer",
    "page_size": "integer"
  }
}
```

### 数据库存储格式

- **Monster表**: 妖怪基础信息和六维属性
- **MonsterDerived表**: 计算得出的五轴派生属性
- **Skill表**: 技能基础信息
- **MonsterSkill表**: 妖怪-技能多对多关联
- **Tag表**: 标签分类信息
- **Collection表**: 收藏夹信息
- **CollectionItem表**: 收藏夹-妖怪关联

### 文件存储格式

- **图片文件**: `images/monsters/{normalized_name}.{ext}`
- **备份文件**: `backups/{timestamp}_backup.db`
- **导出文件**: `exports/{timestamp}_monsters.{csv|json}`
- **日志文件**: `logs/{date}.log`