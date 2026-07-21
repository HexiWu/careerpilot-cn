from __future__ import annotations

import re

SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "Java": ("java",),
    "JavaScript": ("javascript", "js", "typescript"),
    "C++": ("c++", "cpp"),
    "SQL": ("sql", "关系型数据库"),
    "Spark": ("spark", "pyspark", "sparkml"),
    "Airflow": ("airflow",),
    "Hadoop": ("hadoop", "hdfs"),
    "Hive": ("hive",),
    "Flink": ("flink",),
    "Kafka": ("kafka",),
    "Docker": ("docker", "容器化"),
    "Kubernetes": ("kubernetes", "k8s"),
    "AWS": ("aws", "emr", "s3"),
    "Redis": ("redis",),
    "MongoDB": ("mongodb", "mongo"),
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",),
    "FastAPI": ("fastapi",),
    "React": ("react", "next.js", "nextjs"),
    "Git": ("git", "github", "gitlab"),
    "Linux": ("linux", "unix"),
    "Machine Learning": ("machine learning", "机器学习", "模型训练", "ml"),
    "Recommendation": ("推荐系统", "推荐算法", "recommendation", "recommender"),
    "BERT": ("bert",),
    "LLM": ("llm", "大语言模型", "大模型", "langchain", "langgraph", "agent"),
    "Power BI": ("power bi", "powerbi"),
    "Tableau": ("tableau",),
    "ETL": ("etl", "elt", "数据管道", "数据开发"),
    "Data Warehouse": ("数据仓库", "data warehouse", "数仓", "ssas"),
}


ROLE_SIGNALS: dict[str, tuple[str, ...]] = {
    "数据工程师": ("Spark", "Airflow", "SQL", "ETL", "Hadoop"),
    "大数据开发工程师": ("Spark", "Hadoop", "Flink", "Kafka", "Java"),
    "数据平台工程师": ("Airflow", "Docker", "Kubernetes", "AWS", "SQL"),
    "后端开发工程师": ("Python", "Java", "FastAPI", "Redis", "PostgreSQL"),
    "机器学习平台工程师": ("Machine Learning", "Python", "Docker", "AWS", "Spark"),
    "推荐算法工程师": ("Recommendation", "Machine Learning", "Python", "Spark", "BERT"),
    "商业智能工程师": ("SQL", "Power BI", "Tableau", "Data Warehouse", "ETL"),
    "数据分析师": ("SQL", "Python", "Power BI", "Tableau"),
}


CITY_NAMES = (
    "北京",
    "上海",
    "深圳",
    "广州",
    "杭州",
    "武汉",
    "成都",
    "南京",
    "苏州",
    "珠海",
    "西安",
    "重庆",
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for canonical, aliases in SKILL_ALIASES.items():
        if any(_contains_alias(lowered, alias.lower()) for alias in aliases):
            found.append(canonical)
    return found


def _contains_alias(text: str, alias: str) -> bool:
    """Match CJK phrases as substrings and keep token boundaries for Latin aliases."""
    if any("\u4e00" <= character <= "\u9fff" for character in alias):
        return alias in text
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) is not None


def infer_target_roles(skills: list[str], limit: int = 6) -> list[str]:
    skill_set = set(skills)
    ranked = sorted(
        ROLE_SIGNALS.items(),
        key=lambda item: sum(signal in skill_set for signal in item[1]),
        reverse=True,
    )
    return [role for role, signals in ranked if any(s in skill_set for s in signals)][:limit]
