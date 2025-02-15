package com.reely.controller;

import com.reely.dto.MemberDto;
import com.reely.service.AuthService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    @Autowired
    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/join")
    public ResponseEntity<Integer> join(@RequestBody MemberDto memberDto) {
        Integer result = authService.insertMember(memberDto);
        return new ResponseEntity<>(result, HttpStatus.OK);
    }

    @PostMapping("/login")
    public ResponseEntity<Map<String,String>> login(@RequestBody MemberDto memberDto) {
        System.out.printf(memberDto.toString());
        MemberDto  userInfoDto = authService.findMemberInfo(memberDto);
        Map<String, String> userInfo = new HashMap<>();
        userInfo.put("memberId",userInfoDto.getMemberId());
        userInfo.put("memberEmail",userInfoDto.getMemberEmail());

        return ResponseEntity.ok(userInfo);
    }

    @GetMapping("/findAll")
    public ResponseEntity<List<MemberDto>> findAll() {
        List<MemberDto> list = authService.findAll();
        return new ResponseEntity<>(list, HttpStatus.OK);
    }
}
