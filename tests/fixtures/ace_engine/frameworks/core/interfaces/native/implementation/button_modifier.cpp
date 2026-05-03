#include "button_modifier.h"

namespace OHOS::Ace::NG {
void ButtonModifier::SetRole(Ark_UInt32 role)
{
    auto node = GetNode(Ark_NodeHandle);
    CHECK_NULL_VOID(node);
    auto pattern = node->GetPattern<ButtonPattern>();
    // apply role
}

void ButtonModifier::ResetRole()
{
    // reset
}
}
