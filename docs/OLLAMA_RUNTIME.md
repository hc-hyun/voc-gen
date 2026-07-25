# Ollama 로컬 실행 환경

설정과 테스트까지 완료했습니다.

- 모델: `qwen3.5:9b`
- 저장 위치: `D:\OllamaModels`
- 실제 사용량: 약 6.142GB
- C: 모델 사용량: 0GB
- API 주소: `http://127.0.0.1:11434`
- GPU 적재: `100% GPU`
- 컨텍스트: 4096
- 생성 속도: 약 78토큰/초
- 첫 로딩: 약 76초, 이후 요청은 1초 내외
- `OLLAMA_MODELS=D:\OllamaModels` 사용자 환경변수 영구 설정 완료

### OpenAI 호환 API

OpenAI Chat Completions 형식으로 호출할 수 있습니다.

```powershell
$body = @{
    model = "qwen3.5:9b"
    messages = @(
        @{
            role    = "system"
            content = "간결한 한국어로 답하세요."
        },
        @{
            role    = "user"
            content = "대한민국의 수도는?"
        }
    )
    temperature      = 0.2
    max_tokens       = 256
    stream           = $false
    reasoning_effort = "none"
} | ConvertTo-Json -Depth 6

$response = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:11434/v1/chat/completions" `
    -Headers @{ Authorization = "Bearer ollama" } `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($body))

$response.choices[0].message.content
```

테스트 결과:

```text
OpenAI 호환 API 테스트 성공
```

응답 시간은 약 0.87초였습니다.

### Python OpenAI SDK

현재 PC에는 `openai` Python 패키지가 설치되어 있지 않습니다. 사용할 프로젝트 환경에서 설치합니다.

```powershell
python -m pip install openai
```

호출 코드는 다음과 같습니다.

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:11434/v1",
    api_key="ollama",  # 필수 형식이지만 Ollama에서는 검증하지 않음
)

response = client.chat.completions.create(
    model="qwen3.5:9b",
    messages=[
        {
            "role": "system",
            "content": "간결한 한국어로 답하세요.",
        },
        {
            "role": "user",
            "content": "대한민국의 수도는?",
        },
    ],
    temperature=0.2,
    max_tokens=256,
    reasoning_effort="none",
)

print(response.choices[0].message.content)
```

Ollama는 OpenAI API의 `/v1/chat/completions`, `/v1/responses`, `/v1/models` 등을 지원합니다. API 키 문자열은 필요하지만 실제로 검증하지 않습니다. [Ollama OpenAI 호환 API 문서](https://docs.ollama.com/api/openai-compatibility)

### Responses API

이 방식도 실제 테스트해 성공했습니다.

```powershell
$body = @{
    model = "qwen3.5:9b"
    input = "대한민국의 수도는?"
    reasoning = @{
        effort = "none"
    }
    max_output_tokens = 256
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:11434/v1/responses" `
    -Headers @{ Authorization = "Bearer ollama" } `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($body))

$response.output[0].content[0].text
```

테스트 응답 시간은 약 0.67초였습니다.

### Ollama 네이티브 API

OpenAI 호환성이 필요 없다면 이쪽이 Ollama 기능을 가장 직접적으로 사용할 수 있습니다.

```powershell
$body = @{
    model = "qwen3.5:9b"
    messages = @(
        @{
            role    = "user"
            content = "대한민국의 수도는?"
        }
    )
    stream = $false
    think  = $false
    options = @{
        num_ctx    = 4096
        temperature = 0.2
    }
} | ConvertTo-Json -Depth 6

$response = Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:11434/api/chat" `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($body))

$response.message.content
```

추론 과정을 사용하려면 `think = $true`, 끄려면 `think = $false`입니다. [Ollama Thinking 문서](https://docs.ollama.com/capabilities/thinking)

현재 API는 이 PC의 localhost에서만 접근할 수 있는 상태입니다. 상태 확인은 다음 명령으로 할 수 있습니다.

```powershell
ollama list
ollama ps
Invoke-RestMethod http://127.0.0.1:11434/v1/models
```
