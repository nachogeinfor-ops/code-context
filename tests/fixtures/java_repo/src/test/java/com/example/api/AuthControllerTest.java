package com.example.api;

import com.example.api.controllers.AuthController;
import com.example.api.dto.LoginRequest;
import com.example.api.dto.TokenResponse;
import com.example.api.services.AuthService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(AuthController.class)
class AuthControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private AuthService authService;

    @Test
    void loginReturnsTokenPair() throws Exception {
        LoginRequest req = new LoginRequest("alice@example.com", "hunter2123");
        TokenResponse tokens = new TokenResponse("access-jwt", "refresh-jwt", 900L);
        when(authService.login(any())).thenReturn(tokens);

        mockMvc.perform(post("/api/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(req)))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.accessToken").value("access-jwt"))
            .andExpect(jsonPath("$.refreshToken").value("refresh-jwt"));
    }

    @Test
    void refreshReturnsNewTokenPair() throws Exception {
        TokenResponse tokens = new TokenResponse("new-access", "new-refresh", 900L);
        when(authService.refresh("old-refresh")).thenReturn(tokens);

        mockMvc.perform(post("/api/auth/refresh")
                .header("X-Refresh-Token", "old-refresh"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.accessToken").value("new-access"));
    }
}
