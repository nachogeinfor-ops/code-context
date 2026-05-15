package com.example.api;

import com.example.api.controllers.UsersController;
import com.example.api.dto.CreateUserRequest;
import com.example.api.dto.UserResponse;
import com.example.api.services.UserService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import java.time.Instant;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(UsersController.class)
class UsersControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private UserService userService;

    @Test
    void createUserReturns201() throws Exception {
        CreateUserRequest req = new CreateUserRequest("a@b.com", "alice", "hunter2123");
        UserResponse resp = new UserResponse(1L, "a@b.com", "alice", Instant.now());
        when(userService.createUser(any())).thenReturn(resp);

        mockMvc.perform(post("/api/users")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(req)))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.id").value(1));
    }

    @Test
    void listUsersReturnsArray() throws Exception {
        UserResponse u = new UserResponse(1L, "a@b.com", "alice", Instant.now());
        when(userService.listUsers(anyInt(), anyInt())).thenReturn(List.of(u));

        mockMvc.perform(get("/api/users"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$[0].username").value("alice"));
    }
}
