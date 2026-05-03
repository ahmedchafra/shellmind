# shellmind/llm/ollama_client.py
import os
import logging
from typing import Optional, Literal, List
from ollama import Client

logger = logging.getLogger(__name__)

class OllamaClientWrapper:
    """
    Smart Ollama client with local/cloud + multi-model fallback.
    
    Usage:
      - mode="local": only use local
      - mode="cloud": try cloud models in order, fallback to local
    """

    def __init__(
        self,
        mode: Literal["local", "cloud", "auto"] = "local",
        cloud_models: Optional[List[str]] = None,
        local_model: str = "llama3.1:8b-instruct-q4_K_M",
        cloud_api_key: Optional[str] = None
    ) -> None:
        self.mode = mode
        # Use provided models or default cloud model list
        self.cloud_models: List[str] = cloud_models or [
            "gpt-oss:120b",
            "deepseek-v3.1:671b",
            "qwen3-coder:480b",
            "kimi-k2:1t"
        ]
        self.local_model = local_model
        self._local_client = Client(host="http://localhost:11434")
        self._active_client: Optional[Client] = None
        self._active_model: Optional[str] = None
        self._is_cloud = False

        if mode in ("cloud", "auto"):
            api_key = cloud_api_key or os.getenv("OLLAMA_API_KEY")
            if api_key:
                try:
                    # Fixed: no trailing spaces in host
                    self._cloud_client = Client(
                        host="https://ollama.com",
                        headers={"Authorization": f"Bearer {api_key}"}
                    )
                    # Try cloud models in order
                    for model in self.cloud_models:
                        try:
                            self._cloud_client.show(model)
                            self._active_client = self._cloud_client
                            self._active_model = model
                            self._is_cloud = True
                            logger.info(f"✅ Using Ollama Cloud with model: {model}")
                            return
                        except Exception as e:
                            logger.warning(f"☁️ Model {model} unavailable: {e}")
                    # If all cloud models fail, fallback to local
                    logger.warning("☁️ All cloud models failed. Falling back to local.")
                    self._fallback_to_local()
                except Exception as e:
                    logger.warning(f"☁️ Cloud initialization failed: {e}. Falling back to local.")
                    self._fallback_to_local()
            else:
                logger.info("☁️ No OLLAMA_API_KEY → using local")
                self._fallback_to_local()
        else:
            self._fallback_to_local()

    def _fallback_to_local(self) -> None:
        """Switch to local Ollama."""
        self._active_client = self._local_client
        self._active_model: str = self.local_model
        self._is_cloud = False
        logger.info(f"✅ Using Ollama Local with model: {self.local_model}")

    def _try_next_cloud_model(self) -> bool:
        """Try next cloud model after current one fails."""
        if not self._is_cloud or self._active_model is None:
            return False
        
        try:
            current_index = self.cloud_models.index(self._active_model)
        except ValueError:
            logger.warning(f"Current model {self._active_model} not in cloud models list")
            return False

        for model in self.cloud_models[current_index + 1:]:
            try:
                self._cloud_client.show(model)
                self._active_model = model
                logger.info(f"✅ Switched to cloud model: {model}")
                return True
            except Exception as e:
                logger.debug(f"Cloud model {model} unavailable: {e}")
                continue
        return False

    def chat(self, prompt: str, stream: bool = False) -> str:
        """Send prompt and return response."""
        if self._active_client is None or self._active_model is None:
            raise RuntimeError("LLM client not initialized")
        
        messages = [{"role": "user", "content": prompt}]
        try:
            if stream:
                full = ""
                for part in self._active_client.chat(self._active_model, messages=messages, stream=True):
                    chunk: str = part["message"]["content"]
                    print(chunk, end="", flush=True)
                    full += chunk
                print()
                return full
            else:
                response = self._active_client.chat(self._active_model, messages=messages)
                return str(response["message"]["content"]).strip()
        except Exception as e:
            if self._is_cloud:
                logger.warning(f"Cloud model {self._active_model} failed during chat: {e}")
                if self._try_next_cloud_model():
                    return self.chat(prompt, stream=stream)
                else:
                    logger.warning("Falling back to local model.")
                    self._fallback_to_local()
                    return self.chat(prompt, stream=stream)
            else:
                raise RuntimeError(f"Local Ollama failed: {e}. Is 'ollama serve' running?")

    def is_available(self) -> bool:
        """Check if active backend is ready."""
        try:
            if self._is_cloud and self._active_model is not None:
                self._cloud_client.show(self._active_model)
            else:
                self._local_client.ps()
            return True
        except Exception as e:
            logger.debug(f"Backend availability check failed: {e}")
            return False

    @property
    def active_mode(self) -> str:
        return "cloud" if self._is_cloud else "local"

    @property
    def active_model(self) -> str:
        if self._active_model is None:
            raise RuntimeError("Active model not initialized")
        return self._active_model