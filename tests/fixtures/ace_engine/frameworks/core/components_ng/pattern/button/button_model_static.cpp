#include "button_model_static.h"
#include "core/components_ng/pattern/button/button_pattern.h"

namespace OHOS::Ace::NG {
void ButtonModelStatic::SetRole(ButtonRole role)
{
    auto* frameNode = ViewStackProcessor::GetInstance()->GetMainElementNode();
    CHECK_NULL_VOID(frameNode);
    auto pattern = frameNode->GetPattern<ButtonPattern>();
    CHECK_NULL_VOID(pattern);
    // update role property
}

void ButtonModelStatic::SetType(ButtonType type)
{
    // similar pattern
}

void ButtonModelStatic::SetButtonStyle(ButtonStyleMode style)
{
    // similar pattern
}

void ButtonModelStatic::SetControlSize(ControlSize size)
{
    // similar pattern
}
}
