#include "button_modifier.h"

namespace OHOS::Ace::NG {
Ark_Bool ButtonModifier::GetRole(Ark_NodeHandle node)
{
    auto pattern = GetPattern<ButtonPattern>(node);
    CHECK_NULL_RETURN(pattern, ARK_BOOL_FALSE);
    return static_cast<Ark_Bool>(pattern->GetRole());
}

void ButtonModifier::SetRole(Ark_NodeHandle node, Ark_UInt32 role)
{
    auto pattern = GetPattern<ButtonPattern>(node);
    CHECK_NULL_VOID(pattern);
    pattern->SetRole(static_cast<ButtonRole>(role));
}
}
