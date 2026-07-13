#pragma once

#include <atomic>

namespace trench::clean_audio
{

#ifdef TRENCH_PLAYER_EXTRAS
namespace detail
{
inline std::atomic<bool> enabled { true };
}
inline bool kEnabled() noexcept { return detail::enabled.load (std::memory_order_relaxed); }
inline void setEnabled (bool value) noexcept { detail::enabled.store (value, std::memory_order_relaxed); }
#else
constexpr bool kEnabled() noexcept { return false; }
inline void setEnabled (bool) noexcept {}
#endif

inline constexpr const char* kBodyName = "Synthetic identity";

} // namespace trench::clean_audio
