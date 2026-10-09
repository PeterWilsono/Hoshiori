# -*- coding: utf-8 -*-
"""
动态记忆图谱 - Phase 1
三层存储架构：语义层(向量) + 关系层(图谱) + 原始层(JSON)
"""
import json
import math
import re
from datetime import datetime
from typing import List, Dict, Any, Tuple
from collections import defaultdict


class SimpleEmbedding:
    """简化的文本向量化（基于TF-IDF思想）"""
    
    def __init__(self, dim=128):
        self.dim = dim
        self.vocab = {}
        self.idf = {}
    
    def _tokenize(self, text: str) -> List[str]:
        """中文分词（简化版）"""
        # 提取中文词汇（2-4字）
        words = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        # 提取英文单词
        words += re.findall(r'[a-zA-Z]+', text.lower())
        return words
    
    def fit(self, texts: List[str]):
        """构建词汇表和IDF"""
        # 统计词频
        doc_freq = defaultdict(int)
        for text in texts:
            words = set(self._tokenize(text))
            for word in words:
                doc_freq[word] += 1
        
        # 构建词汇表（取前dim个高频词）
        sorted_words = sorted(doc_freq.items(), key=lambda x: x[1], reverse=True)
        self.vocab = {word: idx for idx, (word, _) in enumerate(sorted_words[:self.dim])}
        
        # 计算IDF
        n_docs = len(texts)
        for word, freq in doc_freq.items():
            self.idf[word] = math.log(n_docs / (freq + 1))
    
    def encode(self, text: str) -> List[float]:
        """将文本编码为向量"""
        vector = [0.0] * self.dim
        words = self._tokenize(text)
        
        # 计算TF
        tf = defaultdict(int)
        for word in words:
            tf[word] += 1
        
        # TF-IDF
        for word, count in tf.items():
            if word in self.vocab:
                idx = self.vocab[word]
                vector[idx] = count * self.idf.get(word, 1.0)
        
        # 归一化
        norm = math.sqrt(sum(x**2 for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]
        
        return vector


class VectorMemorySystem:
    """向量记忆系统 - 支持语义检索"""
    
    def __init__(self, dim=128):
        self.dim = dim
        self.embedder = SimpleEmbedding(dim)
        self.memory_vectors = []  # [(vector, memory_data, timestamp)]
        self.memory_index = {}  # memory_id -> index
        self.next_id = 0
    
    def add_memory(self, content: str, metadata: Dict = None) -> int:
        """添加记忆"""
        # 如果embedder还没有词汇表，先用当前文本初始化
        if not self.embedder.vocab:
            self.embedder.fit([content])
        
        vector = self.embedder.encode(content)
        memory_id = self.next_id
        self.next_id += 1
        
        memory_data = {
            "id": memory_id,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(),
            "access_count": 0,
            "strength": 1.0
        }
        
        idx = len(self.memory_vectors)
        self.memory_vectors.append((vector, memory_data, datetime.now()))
        self.memory_index[memory_id] = idx
        
        return memory_id
    
    def search(self, query: str, top_k: int = 5, threshold: float = 0.1) -> List[Dict]:
        """语义搜索"""
        if not self.memory_vectors:
            return []
        
        # 确保query中的词在词汇表中
        query_words = self.embedder._tokenize(query)
        for word in query_words:
            if word not in self.embedder.vocab and word not in self.embedder.idf:
                # 添加新词到词汇表（给予中等IDF值）
                self.embedder.idf[word] = 1.0
        
        query_vector = self.embedder.encode(query)
        
        # 计算相似度
        similarities = []
        for idx, (vector, memory_data, timestamp) in enumerate(self.memory_vectors):
            similarity = self._cosine_similarity(query_vector, vector)
            
            # 应用遗忘曲线
            time_decay = self._calculate_time_decay(timestamp)
            access_boost = 1.0 + 0.1 * memory_data["access_count"]
            
            final_score = similarity * time_decay * access_boost * memory_data["strength"]
            
            if final_score >= threshold:
                similarities.append((idx, final_score, memory_data))
        
        # 排序并返回top_k
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        results = []
        for idx, score, memory_data in similarities[:top_k]:
            # 更新访问计数
            self.memory_vectors[idx][1]["access_count"] += 1
            self.memory_vectors[idx][1]["strength"] = min(1.0, memory_data["strength"] * 1.1)
            
            results.append({
                "content": memory_data["content"],
                "metadata": memory_data["metadata"],
                "similarity": score,
                "memory_id": memory_data["id"]
            })
        
        return results
    
    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """余弦相似度"""
        dot_product = sum(a * b for a, b in zip(v1, v2))
        return max(0, min(1, dot_product))  # 已归一化，直接点积
    
    def _calculate_time_decay(self, timestamp: datetime) -> float:
        """遗忘曲线"""
        hours_passed = (datetime.now() - timestamp).total_seconds() / 3600
        half_life = 168  # 7天半衰期
        return math.exp(-0.693 * hours_passed / half_life)
    
    def update_from_json(self, long_term_memory: Dict):
        """从JSON记忆中构建向量索引"""
        all_texts = []
        
        # 收集所有文本
        for event in long_term_memory.get("emotional_events", []):
            all_texts.append(event.get("event", ""))
        
        for event in long_term_memory.get("important_events", []):
            all_texts.append(event.get("content", ""))
        
        profile = long_term_memory.get("user_profile", {})
        for pref in profile.get("preferences", []):
            if isinstance(pref, dict):
                all_texts.append(pref.get("content", ""))
            else:
                all_texts.append(str(pref))
        
        # 训练embedder
        if all_texts:
            self.embedder.fit(all_texts)
            
            # 添加记忆
            for event in long_term_memory.get("emotional_events", []):
                self.add_memory(
                    event.get("event", ""),
                    {"type": "emotional_event", "importance": event.get("importance", 5)}
                )
            
            for event in long_term_memory.get("important_events", []):
                self.add_memory(
                    event.get("content", ""),
                    {"type": "important_event", "importance": event.get("importance", 7)}
                )


class KnowledgeGraph:
    """知识图谱 - 存储实体和关系"""
    
    def __init__(self):
        self.entities = {}  # entity_id -> {type, name, attributes}
        self.relations = []  # [(entity1_id, relation, entity2_id, weight)]
        self.entity_index = {}  # name -> entity_id
        self.next_id = 0
    
    def add_entity(self, name: str, entity_type: str, attributes: Dict = None) -> int:
        """添加实体"""
        # 检查是否已存在
        if name in self.entity_index:
            return self.entity_index[name]
        
        entity_id = self.next_id
        self.next_id += 1
        
        self.entities[entity_id] = {
            "id": entity_id,
            "name": name,
            "type": entity_type,
            "attributes": attributes or {}
        }
        
        self.entity_index[name] = entity_id
        return entity_id
    
    def add_relation(self, entity1: str, relation: str, entity2: str, weight: float = 1.0):
        """添加关系"""
        # 确保实体存在
        if entity1 not in self.entity_index:
            self.add_entity(entity1, "unknown")
        if entity2 not in self.entity_index:
            self.add_entity(entity2, "unknown")
        
        e1_id = self.entity_index[entity1]
        e2_id = self.entity_index[entity2]
        
        self.relations.append((e1_id, relation, e2_id, weight))
    
    def find_related(self, entity_name: str, max_depth: int = 2) -> List[Dict]:
        """查找相关实体（广度优先搜索）"""
        if entity_name not in self.entity_index:
            return []
        
        start_id = self.entity_index[entity_name]
        visited = {start_id}
        queue = [(start_id, 0)]  # (entity_id, depth)
        related = []
        
        while queue:
            current_id, depth = queue.pop(0)
            
            if depth >= max_depth:
                continue
            
            # 查找所有相关关系
            for e1_id, relation, e2_id, weight in self.relations:
                if e1_id == current_id and e2_id not in visited:
                    visited.add(e2_id)
                    queue.append((e2_id, depth + 1))
                    related.append({
                        "entity": self.entities[e2_id]["name"],
                        "relation": relation,
                        "depth": depth + 1,
                        "weight": weight
                    })
                elif e2_id == current_id and e1_id not in visited:
                    visited.add(e1_id)
                    queue.append((e1_id, depth + 1))
                    related.append({
                        "entity": self.entities[e1_id]["name"],
                        "relation": f"被{relation}",
                        "depth": depth + 1,
                        "weight": weight
                    })
        
        return related
    
    def extract_from_text(self, text: str) -> List[Tuple[str, str, str]]:
        """从文本中提取三元组（简化版NER）"""
        triples = []
        
        # 简单的模式匹配
        patterns = [
            (r'(.{1,6})(喜欢|爱|讨厌|害怕)(.{1,10})', lambda m: (m.group(1).strip(), m.group(2), m.group(3).strip())),
            (r'(.{1,6})(是|叫)(.{1,10})', lambda m: (m.group(1).strip(), m.group(2), m.group(3).strip())),
            (r'(.{1,6})(在|去了|来自)(.{1,10})', lambda m: (m.group(1).strip(), m.group(2), m.group(3).strip())),
            (r'(.{1,6})(有|拥有|买了)(.{1,10})', lambda m: (m.group(1).strip(), m.group(2), m.group(3).strip())),
        ]
        
        for pattern, extractor in patterns:
            for match in re.finditer(pattern, text):
                try:
                    triple = extractor(match)
                    # 过滤掉包含标点的结果
                    if triple and all(len(t) >= 1 and not any(p in t for p in ['，', '。', '！', '？', ',', '.']) for t in triple):
                        triples.append(triple)
                except:
                    continue
        
        return triples


class DynamicMemoryGraph:
    """动态记忆图谱 - 整合向量检索和知识图谱"""
    
    def __init__(self):
        self.vector_system = VectorMemorySystem()
        self.knowledge_graph = KnowledgeGraph()
    
    def add_memory(self, content: str, memory_type: str = "general", importance: int = 5):
        """添加记忆（同时更新向量和图谱）"""
        # 如果向量系统还没初始化，先用当前内容初始化
        if not self.vector_system.embedder.vocab:
            self.vector_system.embedder.fit([content])
        
        # 添加到向量系统
        memory_id = self.vector_system.add_memory(content, {
            "type": memory_type,
            "importance": importance
        })
        
        # 提取知识图谱三元组
        triples = self.knowledge_graph.extract_from_text(content)
        for entity1, relation, entity2 in triples:
            self.knowledge_graph.add_relation(entity1, relation, entity2)
        
        return memory_id
    
    def search_with_association(self, query: str, top_k: int = 5) -> List[Dict]:
        """联想式检索（向量 + 图谱扩展）"""
        # 1. 向量检索
        vector_results = self.vector_system.search(query, top_k=top_k)
        
        # 2. 图谱扩展
        graph_results = []
        query_entities = self.knowledge_graph.extract_from_text(query)
        
        for entity1, _, entity2 in query_entities:
            # 查找相关实体
            related = self.knowledge_graph.find_related(entity1, max_depth=2)
            related += self.knowledge_graph.find_related(entity2, max_depth=2)
            
            for rel in related:
                graph_results.append({
                    "content": f"{rel['entity']} ({rel['relation']})",
                    "metadata": {"type": "graph_association", "depth": rel["depth"]},
                    "similarity": 0.5 * rel["weight"] / rel["depth"]
                })
        
        # 3. 合并结果
        all_results = vector_results + graph_results
        
        # 去重并排序
        seen = set()
        unique_results = []
        for result in sorted(all_results, key=lambda x: x["similarity"], reverse=True):
            content = result["content"]
            if content not in seen:
                seen.add(content)
                unique_results.append(result)
        
        return unique_results[:top_k]
    
    def build_from_json(self, long_term_memory: Dict):
        """从JSON记忆构建图谱"""
        self.vector_system.update_from_json(long_term_memory)
        
        # 构建知识图谱
        for event in long_term_memory.get("emotional_events", []):
            content = event.get("event", "")
            triples = self.knowledge_graph.extract_from_text(content)
            for e1, rel, e2 in triples:
                self.knowledge_graph.add_relation(e1, rel, e2)
        
        for event in long_term_memory.get("important_events", []):
            content = event.get("content", "")
            triples = self.knowledge_graph.extract_from_text(content)
            for e1, rel, e2 in triples:
                self.knowledge_graph.add_relation(e1, rel, e2)
